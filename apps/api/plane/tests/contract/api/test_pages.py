# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Contract tests for project pages in /api/v1 (fork Liviere/plane, plane/liviere/api).
# Adapted from makeplane/plane#9528 (RemoYukoff) and #9774 (rclod).

from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Page, Project, ProjectMember, ProjectPage, User
from plane.db.models.api import APIToken

VIEWS = "plane.liviere.api.views"

# Keys plane-sdk 0.3.1 requires in a paginated response
PAGINATION_KEYS = {
    "total_count",
    "next_cursor",
    "prev_cursor",
    "next_page_results",
    "prev_page_results",
    "count",
    "total_pages",
    "total_results",
    "results",
}


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Test Project",
        identifier="TP",
        workspace=workspace,
        created_by=create_user,
        page_view=True,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


def _make_user(prefix):
    unique_id = uuid4().hex[:8]
    user = User.objects.create(
        email=f"{prefix}-{unique_id}@plane.so",
        username=f"{prefix}_{unique_id}",
    )
    user.set_password(uuid4().hex)
    user.save()
    return user


def _client_for(user, project, role):
    ProjectMember.objects.create(project=project, member=user, role=role, is_active=True)
    token = APIToken.objects.create(user=user, label=f"role {role}", token=f"plane_api_{uuid4().hex}")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token.token)
    return client


@pytest.fixture
def other_user(db):
    return _make_user("other")


@pytest.fixture
def member_client(db, project, other_user):
    """API client of a project member (role 15) who is not the admin."""
    return _client_for(other_user, project, 15)


@pytest.fixture
def guest_user(db):
    return _make_user("guest")


@pytest.fixture
def guest_client(db, project, guest_user):
    return _client_for(guest_user, project, 5)


def _make_page(project, owner, access=Page.PUBLIC_ACCESS, **kwargs):
    page = Page.objects.create(
        workspace=project.workspace,
        owned_by=owner,
        access=access,
        name=kwargs.pop("name", "Helper Page"),
        **kwargs,
    )
    ProjectPage.objects.create(workspace=project.workspace, project=project, page=page)
    return page


def _list_url(workspace, project):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/pages/"


def _detail_url(workspace, project, page):
    return f"{_list_url(workspace, project)}{page.id}/"


def _archive_url(workspace, project, page):
    return f"{_detail_url(workspace, project, page)}archive/"


@pytest.mark.contract
class TestPageListCreate:
    @pytest.mark.django_db
    def test_create_page(self, api_key_client, workspace, project, create_user, django_capture_on_commit_callbacks):
        payload = {"name": "Spec", "description_html": "<h1>Spec</h1><p>Body</p>", "access": 1}
        with patch(f"{VIEWS}.page_transaction") as mock_transaction:
            with django_capture_on_commit_callbacks(execute=True):
                response = api_key_client.post(_list_url(workspace, project), payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        page = Page.objects.get(pk=response.data["id"])
        assert page.name == "Spec"
        assert page.description_html == "<h1>Spec</h1><p>Body</p>"
        assert page.description_binary is None
        assert page.description_json == {}
        assert page.owned_by_id == create_user.id
        assert page.access == Page.PRIVATE_ACCESS
        assert ProjectPage.objects.filter(page=page, project=project).exists()
        assert response.data["projects"] == [str(project.id)]
        assert response.data["description_html"] == "<h1>Spec</h1><p>Body</p>"
        mock_transaction.delay.assert_called_once()

    @pytest.mark.django_db
    def test_create_requires_name(self, api_key_client, workspace, project):
        response = api_key_client.post(_list_url(workspace, project), {"description_html": "<p>x</p>"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Page.objects.count() == 0

    @pytest.mark.django_db
    def test_create_ignores_server_fields(self, api_key_client, workspace, project, create_user, other_user):
        payload = {
            "name": "Spec",
            "description_html": "<p>x</p>",
            "owned_by": str(other_user.id),
            "archived_at": "2024-01-01",
            "description_binary": "AAAAAAAA",
            "description_json": {"type": "doc"},
            "view_props": {"full_width": True},
        }
        response = api_key_client.post(_list_url(workspace, project), payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        page = Page.objects.get(pk=response.data["id"])
        assert page.owned_by_id == create_user.id
        assert page.archived_at is None
        assert page.description_binary is None
        assert page.description_json == {}
        assert page.view_props == {"full_width": False}

    @pytest.mark.django_db
    def test_create_sanitizes_html(self, api_key_client, workspace, project):
        payload = {"name": "XSS", "description_html": "<p>ok</p><script>alert(1)</script>"}
        response = api_key_client.post(_list_url(workspace, project), payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert "<script" not in Page.objects.get(pk=response.data["id"]).description_html

    @pytest.mark.django_db
    def test_create_external_id_conflict(self, api_key_client, workspace, project):
        payload = {"name": "Imported", "description_html": "<p>x</p>", "external_id": "1", "external_source": "asana"}
        first = api_key_client.post(_list_url(workspace, project), payload, format="json")
        second = api_key_client.post(_list_url(workspace, project), payload, format="json")

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()["id"] == first.json()["id"]
        assert Page.objects.count() == 1

    @pytest.mark.django_db
    def test_create_with_parent_id(self, api_key_client, workspace, project, create_user):
        parent = _make_page(project, create_user, name="Parent")
        payload = {"name": "Child", "description_html": "<p>x</p>", "parent_id": str(parent.id)}
        response = api_key_client.post(_list_url(workspace, project), payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["parent_id"] == str(parent.id)
        assert Page.objects.get(pk=response.data["id"]).parent_id == parent.id

    @pytest.mark.django_db
    def test_create_rejects_parent_from_other_project(self, api_key_client, workspace, project, create_user):
        other_project = Project.objects.create(name="Other", identifier="OP", workspace=workspace)
        foreign = _make_page(other_project, create_user, name="Foreign")
        payload = {"name": "Child", "description_html": "<p>x</p>", "parent_id": str(foreign.id)}
        response = api_key_client.post(_list_url(workspace, project), payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "parent_id" in response.data

    @pytest.mark.django_db
    def test_list_pagination_envelope(self, api_key_client, workspace, project, create_user):
        _make_page(project, create_user, name="One")
        response = api_key_client.get(_list_url(workspace, project), {"per_page": 10})

        assert response.status_code == status.HTTP_200_OK
        assert PAGINATION_KEYS <= set(response.data)
        assert response.data["total_count"] == 1
        page = response.data["results"][0]
        for key in ("id", "name", "owned_by", "access", "is_locked", "archived_at", "parent_id", "projects"):
            assert key in page

    @pytest.mark.django_db
    def test_list_visibility(self, api_key_client, workspace, project, create_user, other_user):
        _make_page(project, other_user, access=Page.PRIVATE_ACCESS, name="Their private")
        _make_page(project, other_user, name="Their public")
        _make_page(project, create_user, access=Page.PRIVATE_ACCESS, name="My private")
        parent = _make_page(project, create_user, name="Parent")
        _make_page(project, create_user, name="Nested", parent=parent)
        _make_page(project, create_user, name="Archived", archived_at=timezone.now().date())

        response = api_key_client.get(_list_url(workspace, project))
        names = {page["name"] for page in response.data["results"]}

        assert names == {"Their public", "My private", "Parent", "Nested", "Archived"}

    @pytest.mark.django_db
    def test_list_filter_by_external_id(self, api_key_client, workspace, project, create_user):
        _make_page(project, create_user, name="A", external_id="a", external_source="asana")
        _make_page(project, create_user, name="B", external_id="b", external_source="asana")
        response = api_key_client.get(_list_url(workspace, project), {"external_id": "b"})

        assert [page["name"] for page in response.data["results"]] == ["B"]

    @pytest.mark.django_db
    def test_guest_sees_only_own_pages(self, guest_client, workspace, project, create_user, guest_user):
        _make_page(project, create_user, name="Admin public")
        _make_page(project, guest_user, name="Guest own")

        response = guest_client.get(_list_url(workspace, project))
        assert {page["name"] for page in response.data["results"]} == {"Guest own"}

        project.guest_view_all_features = True
        project.save()
        response = guest_client.get(_list_url(workspace, project))
        assert {page["name"] for page in response.data["results"]} == {"Admin public", "Guest own"}

    @pytest.mark.django_db
    def test_guest_cannot_create(self, guest_client, workspace, project):
        response = guest_client.post(
            _list_url(workspace, project), {"name": "x", "description_html": "<p>x</p>"}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_non_member_denied(self, workspace, project):
        client = APIClient()
        token = APIToken.objects.create(user=_make_user("outsider"), label="x", token=f"plane_api_{uuid4().hex}")
        client.credentials(HTTP_X_API_KEY=token.token)
        assert client.get(_list_url(workspace, project)).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.contract
class TestPageDetail:
    @pytest.mark.django_db
    def test_retrieve(self, api_key_client, workspace, project, create_user):
        page = _make_page(project, create_user, name="Doc", description_html="<p>Body</p>")
        response = api_key_client.get(_detail_url(workspace, project, page))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(page.id)
        assert response.data["description_html"] == "<p>Body</p>"
        assert response.data["projects"] == [str(project.id)]
        assert "description_binary" not in response.data

    @pytest.mark.django_db
    def test_other_users_private_page_hidden(self, api_key_client, workspace, project, other_user):
        page = _make_page(project, other_user, access=Page.PRIVATE_ACCESS)
        response = api_key_client.get(_detail_url(workspace, project, page))
        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    @pytest.mark.django_db
    def test_put_is_partial(self, api_key_client, workspace, project, create_user):
        page = _make_page(project, create_user, name="Old", description_html="<p>Keep</p>")
        page.description_binary = b"\x01\x02\x03\x04"
        page.save()

        response = api_key_client.put(_detail_url(workspace, project, page), {"name": "New"}, format="json")

        assert response.status_code == status.HTTP_200_OK
        page.refresh_from_db()
        assert page.name == "New"
        assert page.description_html == "<p>Keep</p>"
        assert bytes(page.description_binary) == b"\x01\x02\x03\x04"

    @pytest.mark.parametrize("method", ["put", "patch"])
    @pytest.mark.django_db
    def test_content_update_resets_editor_state(
        self, method, api_key_client, workspace, project, create_user, django_capture_on_commit_callbacks
    ):
        # Never opened in the editor: no Yjs binary yet
        page = _make_page(project, create_user, description_html="<p>Old</p>", description_json={"type": "doc"})

        with (
            patch(f"{VIEWS}.page_transaction") as mock_transaction,
            patch(f"{VIEWS}.track_page_version") as mock_version,
        ):
            with django_capture_on_commit_callbacks(execute=True):
                response = getattr(api_key_client, method)(
                    _detail_url(workspace, project, page), {"description_html": "<p>New</p>"}, format="json"
                )

        assert response.status_code == status.HTTP_200_OK
        page.refresh_from_db()
        assert page.description_html == "<p>New</p>"
        assert page.description_binary is None
        assert page.description_json == {}
        assert response.data["description_html"] == "<p>New</p>"
        mock_transaction.delay.assert_called_once()
        mock_version.delay.assert_called_once()
        assert "<p>Old</p>" in mock_version.delay.call_args.kwargs["existing_instance"]

    @pytest.mark.parametrize("method", ["put", "patch"])
    @pytest.mark.django_db
    def test_content_update_refused_after_page_was_opened(
        self, method, api_key_client, workspace, project, create_user
    ):
        # live stores description_binary on first open; rewriting the HTML then would be
        # overwritten by an open editor or duplicated by a browser's cached document
        page = _make_page(project, create_user, name="Old", description_html="<p>Old</p>")
        page.description_binary = b"\x01\x02\x03\x04"
        page.save()

        response = getattr(api_key_client, method)(
            _detail_url(workspace, project, page), {"name": "New", "description_html": "<p>New</p>"}, format="json"
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        page.refresh_from_db()
        assert page.name == "Old"
        assert page.description_html == "<p>Old</p>"
        assert bytes(page.description_binary) == b"\x01\x02\x03\x04"

    @pytest.mark.django_db
    def test_unchanged_content_keeps_editor_state(self, api_key_client, workspace, project, create_user):
        page = _make_page(project, create_user, description_html="<p>Same</p>")
        page.description_binary = b"\x01\x02\x03\x04"
        page.save()

        response = api_key_client.put(
            _detail_url(workspace, project, page), {"description_html": "<p>Same</p>"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        page.refresh_from_db()
        assert bytes(page.description_binary) == b"\x01\x02\x03\x04"

    @pytest.mark.django_db
    def test_locked_page_refused(self, api_key_client, workspace, project, create_user):
        page = _make_page(project, create_user, is_locked=True)

        response = api_key_client.put(_detail_url(workspace, project, page), {"name": "New"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        response = api_key_client.patch(_detail_url(workspace, project, page), {"is_locked": False}, format="json")
        assert response.status_code == status.HTTP_200_OK
        page.refresh_from_db()
        assert page.is_locked is False

    @pytest.mark.django_db
    def test_archived_page_refused(self, api_key_client, workspace, project, create_user):
        page = _make_page(project, create_user, archived_at=timezone.now().date())
        response = api_key_client.put(
            _detail_url(workspace, project, page), {"description_html": "<p>x</p>"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_access_change_only_by_owner(self, member_client, workspace, project, create_user, other_user):
        theirs = _make_page(project, create_user)
        response = member_client.patch(_detail_url(workspace, project, theirs), {"access": 1}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        own = _make_page(project, other_user)
        response = member_client.patch(_detail_url(workspace, project, own), {"access": "1"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        own.refresh_from_db()
        assert own.access == Page.PRIVATE_ACCESS

    @pytest.mark.django_db
    def test_parent_cannot_be_descendant(self, api_key_client, workspace, project, create_user):
        parent = _make_page(project, create_user, name="Parent")
        child = _make_page(project, create_user, name="Child", parent=parent)

        response = api_key_client.patch(
            _detail_url(workspace, project, parent), {"parent_id": str(child.id)}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        response = api_key_client.patch(
            _detail_url(workspace, project, parent), {"parent_id": str(parent.id)}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_guest_can_update_own_page_like_ui(self, guest_client, workspace, project, guest_user):
        # ProjectPagePermission lets the owner through whatever the role, as in the UI
        page = _make_page(project, guest_user)
        response = guest_client.put(_detail_url(workspace, project, page), {"name": "x"}, format="json")
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    def test_guest_cannot_update_others_page(self, guest_client, workspace, project, create_user):
        project.guest_view_all_features = True
        project.save()
        page = _make_page(project, create_user)
        response = guest_client.put(_detail_url(workspace, project, page), {"name": "x"}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_delete_requires_archive(self, api_key_client, workspace, project, create_user):
        page = _make_page(project, create_user)

        response = api_key_client.delete(_detail_url(workspace, project, page))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"] == "The page should be archived before deleting"

        assert api_key_client.post(_archive_url(workspace, project, page)).status_code == status.HTTP_200_OK
        assert api_key_client.delete(_detail_url(workspace, project, page)).status_code == status.HTTP_204_NO_CONTENT
        assert not Page.objects.filter(pk=page.id).exists()

    @pytest.mark.django_db
    def test_member_cannot_delete_others_page(self, member_client, workspace, project, create_user):
        page = _make_page(project, create_user, archived_at=timezone.now().date())
        response = member_client.delete(_detail_url(workspace, project, page))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert Page.objects.filter(pk=page.id).exists()


@pytest.mark.contract
class TestPageArchive:
    @pytest.mark.django_db
    def test_archive_and_unarchive_include_descendants(self, api_key_client, workspace, project, create_user):
        parent = _make_page(project, create_user, name="Parent")
        child = _make_page(project, create_user, name="Child", parent=parent)

        response = api_key_client.post(_archive_url(workspace, project, parent))
        assert response.status_code == status.HTTP_200_OK
        parent.refresh_from_db()
        child.refresh_from_db()
        assert parent.archived_at is not None
        assert child.archived_at is not None

        response = api_key_client.delete(_archive_url(workspace, project, parent))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        parent.refresh_from_db()
        child.refresh_from_db()
        assert parent.archived_at is None
        assert child.archived_at is None

    @pytest.mark.django_db
    def test_unarchive_detaches_archived_parent(self, api_key_client, workspace, project, create_user):
        today = timezone.now().date()
        parent = _make_page(project, create_user, name="Parent", archived_at=today)
        child = _make_page(project, create_user, name="Child", parent=parent, archived_at=today)

        response = api_key_client.delete(_archive_url(workspace, project, child))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        child.refresh_from_db()
        assert child.parent_id is None
        assert child.archived_at is None

    @pytest.mark.django_db
    def test_member_cannot_archive_others_page(self, member_client, workspace, project, create_user):
        page = _make_page(project, create_user)
        response = member_client.post(_archive_url(workspace, project, page))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        page.refresh_from_db()
        assert page.archived_at is None
