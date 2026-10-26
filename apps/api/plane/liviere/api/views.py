# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Project pages in the public API (/api/v1), following the contract of plane-sdk 0.3.1.
# Based on makeplane/plane#9528 (RemoYukoff); guest scoping and content reset from #9774
# (rclod), the archived-page check from #8865 (nprodromou). Semantics mirror
# plane/app/views/page/base.py (PageViewSet, PagesDescriptionViewSet).

# Python imports
import json
from datetime import datetime

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Prefetch, Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ROLE, ProjectPagePermission
from plane.app.views.page.base import unarchive_archive_page_and_descendants
from plane.bgtasks.page_transaction_task import page_transaction
from plane.bgtasks.page_version_task import track_page_version
from plane.db.models import Page, Project, ProjectMember, ProjectPage, UserFavorite, UserRecentVisit

from .serializers import WRITABLE_FIELDS, PageDetailSerializer, PageSerializer


def project_pages(slug, project_id, user):
    """Pages of the project visible to the user, like PageViewSet: public ones and own private ones."""
    queryset = (
        Page.objects.filter(
            workspace__slug=slug,
            project_pages__project_id=project_id,
            project_pages__deleted_at__isnull=True,
            project_pages__project__archived_at__isnull=True,
        )
        .filter(Q(owned_by=user) | Q(access=Page.PUBLIC_ACCESS))
        .prefetch_related(
            Prefetch(
                "project_pages",
                queryset=ProjectPage.objects.filter(deleted_at__isnull=True),
                to_attr="active_project_pages",
            )
        )
        .order_by("-created_at")
    )

    # A guest sees only own pages unless the project shares all features with guests
    member = ProjectMember.objects.filter(
        workspace__slug=slug, project_id=project_id, member=user, is_active=True
    ).first()
    if member and member.role == ROLE.GUEST.value:
        project = Project.objects.get(pk=project_id)
        if not project.guest_view_all_features:
            queryset = queryset.filter(owned_by=user)
    return queryset


def is_owner_or_admin(request, page, project_id):
    return (
        page.owned_by_id == request.user.id
        or ProjectMember.objects.filter(
            project_id=project_id, member=request.user, is_active=True, role=ROLE.ADMIN.value
        ).exists()
    )


def external_id_conflict(slug, project_id, external_id, external_source, exclude_id=None):
    queryset = Page.objects.filter(
        workspace__slug=slug,
        project_pages__project_id=project_id,
        project_pages__deleted_at__isnull=True,
        external_id=external_id,
        external_source=external_source,
    )
    if exclude_id:
        queryset = queryset.exclude(pk=exclude_id)
    return queryset.first()


class PageListCreateAPIEndpoint(BaseAPIView):
    """List and create project pages."""

    model = Page
    serializer_class = PageSerializer
    permission_classes = [ProjectPagePermission]
    use_read_replica = True

    def get(self, request, slug, project_id):
        queryset = project_pages(slug, project_id, request.user)
        for field in ("external_id", "external_source"):
            if request.GET.get(field):
                queryset = queryset.filter(**{field: request.GET.get(field)})
        return self.paginate(
            request=request,
            queryset=queryset,
            on_results=lambda pages: PageSerializer(pages, many=True, fields=self.fields, expand=self.expand).data,
        )

    def post(self, request, slug, project_id):
        data = {key: value for key, value in request.data.items() if key in WRITABLE_FIELDS}
        serializer = PageDetailSerializer(
            data=data,
            context={"project_id": project_id, "user_id": request.user.id},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        external_id = serializer.validated_data.get("external_id")
        external_source = serializer.validated_data.get("external_source")
        if external_id and external_source:
            existing = external_id_conflict(slug, project_id, external_id, external_source)
            if existing:
                return Response(
                    {
                        "error": "Page with the same external id and external source already exists",
                        "id": str(existing.id),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        with transaction.atomic():
            page = serializer.save()
            transaction.on_commit(
                lambda: page_transaction.delay(
                    new_description_html=page.description_html,
                    old_description_html=None,
                    page_id=str(page.id),
                )
            )

        page = project_pages(slug, project_id, request.user).get(pk=page.id)
        return Response(PageDetailSerializer(page).data, status=status.HTTP_201_CREATED)


class PageDetailAPIEndpoint(BaseAPIView):
    """Retrieve, update (PUT and PATCH, both partial) and delete a project page."""

    model = Page
    serializer_class = PageDetailSerializer
    permission_classes = [ProjectPagePermission]
    use_read_replica = True

    def get(self, request, slug, project_id, page_id):
        page = project_pages(slug, project_id, request.user).get(pk=page_id)
        return Response(
            PageDetailSerializer(page, fields=self.fields, expand=self.expand).data,
            status=status.HTTP_200_OK,
        )

    def put(self, request, slug, project_id, page_id):
        # plane-sdk sends updates as PUT with only the changed fields
        return self.patch(request, slug, project_id, page_id)

    def patch(self, request, slug, project_id, page_id):
        page = project_pages(slug, project_id, request.user).get(pk=page_id)
        data = {key: value for key, value in request.data.items() if key in WRITABLE_FIELDS}

        if page.archived_at:
            return Response({"error": "Archived page cannot be edited"}, status=status.HTTP_400_BAD_REQUEST)

        # A locked page can only be unlocked (the internal unlock has the same permissions)
        if page.is_locked and set(data) - {"is_locked"}:
            return Response({"error": "Page is locked"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = PageDetailSerializer(
            page,
            data=data,
            partial=True,
            context={"project_id": project_id, "user_id": request.user.id},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        validated = serializer.validated_data

        # Only the owner can change the access
        if "access" in validated and validated["access"] != page.access and page.owned_by_id != request.user.id:
            return Response(
                {"error": "Access cannot be updated since this page is owned by someone else"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        external_id = validated.get("external_id", page.external_id)
        external_source = validated.get("external_source", page.external_source)
        if ("external_id" in validated or "external_source" in validated) and external_id and external_source:
            existing = external_id_conflict(slug, project_id, external_id, external_source, exclude_id=page.id)
            if existing:
                return Response(
                    {
                        "error": "Page with the same external id and external source already exists",
                        "id": str(existing.id),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        # Unchanged content is not a content write: keep the editor state as it is
        if validated.get("description_html") == page.description_html:
            validated.pop("description_html")

        old_description_html = page.description_html
        content_changed = "description_html" in validated

        # The live server stores the Yjs state (description_binary) as soon as a page is opened
        # in the editor. Once it exists, replacing the HTML and clearing the binary is not safe:
        # an open editor stores its state over the change, and a browser with the page cached
        # (y-indexeddb) merges its old document with the one rebuilt from HTML, duplicating the
        # content. So content can only be written until the page is first opened.
        if content_changed and page.description_binary:
            return Response(
                {
                    "error": "The page has been opened in the editor; its content can only be changed "
                    "there. Nothing was written."
                },
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            page = serializer.save()
            if content_changed:
                existing_instance = json.dumps({"description_html": old_description_html}, cls=DjangoJSONEncoder)
                new_description_html = page.description_html
                transaction.on_commit(
                    lambda: (
                        page_transaction.delay(
                            new_description_html=new_description_html,
                            old_description_html=old_description_html,
                            page_id=str(page_id),
                        ),
                        track_page_version.delay(
                            page_id=str(page_id),
                            existing_instance=existing_instance,
                            user_id=str(request.user.id),
                        ),
                    )
                )

        page = project_pages(slug, project_id, request.user).get(pk=page_id)
        return Response(PageDetailSerializer(page).data, status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, page_id):
        page = project_pages(slug, project_id, request.user).get(pk=page_id)

        if page.archived_at is None:
            return Response(
                {"error": "The page should be archived before deleting"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not is_owner_or_admin(request, page, project_id):
            return Response(
                {"error": "Only admin or owner can delete the page"},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            # Detach the children, like the internal destroy
            Page.objects.filter(
                parent_id=page_id,
                projects__id=project_id,
                workspace__slug=slug,
                project_pages__deleted_at__isnull=True,
            ).update(parent=None)
            page.delete()
            UserFavorite.objects.filter(
                project=project_id,
                workspace__slug=slug,
                entity_identifier=page_id,
                entity_type="page",
            ).delete()
            UserRecentVisit.objects.filter(
                project_id=project_id,
                workspace__slug=slug,
                entity_identifier=page_id,
                entity_name="page",
            ).delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PageArchiveUnarchiveAPIEndpoint(BaseAPIView):
    """Archive (POST) and unarchive (DELETE) a page together with its nested pages."""

    model = Page
    permission_classes = [ProjectPagePermission]

    def post(self, request, slug, project_id, page_id):
        page = project_pages(slug, project_id, request.user).get(pk=page_id)
        if not is_owner_or_admin(request, page, project_id):
            return Response(
                {"error": "Only the owner or admin can archive the page"},
                status=status.HTTP_403_FORBIDDEN,
            )

        UserFavorite.objects.filter(
            entity_type="page",
            entity_identifier=page_id,
            project_id=project_id,
            workspace__slug=slug,
        ).delete()
        archived_at = datetime.now()
        unarchive_archive_page_and_descendants(page_id, archived_at)
        return Response({"archived_at": str(archived_at)}, status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, page_id):
        page = project_pages(slug, project_id, request.user).get(pk=page_id)
        if not is_owner_or_admin(request, page, project_id):
            return Response(
                {"error": "Only the owner or admin can unarchive the page"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # An archived parent would leave the page hidden: detach it, like the internal unarchive
        if page.parent_id and page.parent.archived_at:
            page.parent = None
            page.save(update_fields=["parent"])

        unarchive_archive_page_and_descendants(page_id, None)
        return Response(status=status.HTTP_204_NO_CONTENT)
