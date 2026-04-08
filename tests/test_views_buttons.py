# ollim-bot
# Copyright (C) 2025-2026 Julius Frost
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Tests for views.py button handlers — event_del backward compat."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ollim_bot import views


@pytest.fixture()
def interaction():
    mock = MagicMock()
    mock.response = MagicMock()
    mock.response.send_message = AsyncMock()
    return mock


class TestEventDeleteButtonCompat:
    """Button handler parses calendar_id/event_id with split('/', 1)."""

    @pytest.mark.anyio()
    async def test_old_format_falls_back_to_primary(self, interaction):
        """Old buttons encode just event_id — fall back to primary."""
        with (
            patch.object(views, "delete_event", return_value="Test Event") as mock_del,
            patch.object(views, "append_update", new_callable=AsyncMock),
        ):
            await views._handle_event_delete(interaction, "abc123")
            mock_del.assert_called_once_with("abc123", "primary")

    @pytest.mark.anyio()
    async def test_new_format_extracts_calendar_id(self, interaction):
        """New buttons encode calendar_id/event_id."""
        with (
            patch.object(views, "delete_event", return_value="Test Event") as mock_del,
            patch.object(views, "append_update", new_callable=AsyncMock),
        ):
            await views._handle_event_delete(interaction, "work@group.calendar.google.com/abc123")
            mock_del.assert_called_once_with("abc123", "work@group.calendar.google.com")
