"""Tests for export handler functions."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.models.actual_event import ActualEvent
from app.db.models.association import Association
from app.db.models.note import Note
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.vision import Vision
from app.handlers import user_preferences as user_preferences_service
from app.handlers.associations_async import LinkType, ModelName
from app.handlers.exports.notes_export import export_notes_data
from app.handlers.exports.planning_export import export_planning_data
from app.handlers.exports.timelog_export import (
    ActualEventExportService,
    export_timelog_data,
)
from app.handlers.exports.vision_export import VisionExportService, export_vision_data
from app.schemas.export import (
    NotesExportParams,
    PlanningExportParams,
    TimeLogExportParams,
    VisionExportParams,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("engine")]


class TestExportHandlers:
    """Backend export handler tests."""

    @pytest.mark.asyncio
    async def test_export_notes_data_advanced_filters(
        self, async_db_session, monkeypatch
    ):
        user = User(
            id=uuid4(),
            email="notes@example.com",
            name="Notes User",
            password_hash="hashed",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=user.id,
            key="system.language",
            value="zh",
            module="system",
        )

        captured_request = {}

        async def fake_advanced_search(db, *, user_id, request):
            captured_request["request"] = request
            note = SimpleNamespace(
                id=uuid4(),
                user_id=user_id,
                content="测试笔记",
                created_at=datetime(2025, 1, 1, 12, 0, 0),
                persons=[SimpleNamespace(display_name="Alice", primary_nickname=None)],
                tags=[SimpleNamespace(name="TagA")],
            )
            return [(note, note.persons, None)]

        monkeypatch.setattr(
            "app.handlers.exports.notes_export.advanced_search_notes",
            fake_advanced_search,
        )

        tag_ids = [uuid4(), uuid4()]
        person_ids = [uuid4()]

        params = NotesExportParams(
            selected_filter_tags=[
                {"id": str(tag_ids[0]), "name": "TagA"},
                {"id": str(tag_ids[1]), "name": "TagB"},
            ],
            selected_filter_persons=[
                {"id": str(person_ids[0]), "display_name": "Alice"}
            ],
            search_keyword="思考",
        )

        export_text = await export_notes_data(
            async_db_session, params=params, user_id=str(user.id)
        )

        assert "Alice" in export_text
        captured = captured_request["request"]
        assert captured.tag_ids and set(captured.tag_ids) == set(tag_ids)
        assert captured.person_ids and set(captured.person_ids) == set(person_ids)

    @pytest.mark.asyncio
    async def test_export_timelog_data_includes_related_entities(
        self, async_db_session, monkeypatch
    ):
        user = User(
            id=uuid4(),
            email="timelog@example.com",
            name="Time User",
            password_hash="hashed",
        )
        async_db_session.add(user)
        await async_db_session.commit()
        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=user.id,
            key="system.language",
            value="zh",
            module="system",
        )

        async def fake_convert_range(*args, **kwargs):
            start = datetime(2025, 6, 1, 0, 0, 0)
            end = datetime(2025, 6, 1, 23, 59, 59)
            return start, end

        monkeypatch.setattr(
            "app.handlers.exports.timelog_export.user_preferences_service.convert_date_range_to_timezone",
            fake_convert_range,
        )

        async def fake_search_events(*args, **kwargs):
            event = SimpleNamespace(
                start_time=datetime(2025, 6, 1, 9, 0, 0),
                end_time=datetime(2025, 6, 1, 10, 30, 0),
                dimension_id=None,
                title="深度工作",
            )
            person_summary = {"display_name": "Bob"}
            task_summary = {
                "content": "整理任务列表",
                "status": "in_progress",
                "vision_summary": {"name": "效率提升计划"},
            }
            setattr(event, "export_person_summaries", [person_summary])
            setattr(event, "export_task_summary", task_summary)
            return (
                [event],
                {
                    "limit": 1000,
                    "total_count": 1,
                    "returned_count": 1,
                    "truncated": False,
                },
            )

        monkeypatch.setattr(
            "app.handlers.exports.timelog_export._search_events_for_export",
            fake_search_events,
        )

        params = TimeLogExportParams(
            start_date=datetime(2025, 6, 1, 0, 0, 0),
            end_date=datetime(2025, 6, 1, 0, 0, 0),
        )

        export_text, metadata = await export_timelog_data(
            async_db_session, params=params, user_id=str(user.id)
        )

        assert "整理任务列表" in export_text
        assert "愿景: 效率提升计划" in export_text
        assert "状态: 进行中" in export_text
        assert "Bob" in export_text
        assert "1小时 30分钟" in export_text
        assert metadata["total_count"] == 1

    @pytest.mark.asyncio
    async def test_export_timelog_data_respects_english_preference(
        self, async_db_session, monkeypatch
    ):
        user = User(
            id=uuid4(),
            email="timelog-en@example.com",
            name="Time EN User",
            password_hash="hashed",
        )
        async_db_session.add(user)
        await async_db_session.commit()
        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=user.id,
            key="system.language",
            value="en",
            module="system",
        )

        async def fake_convert_range(*args, **kwargs):
            start = datetime(2025, 6, 1, 0, 0, 0)
            end = datetime(2025, 6, 1, 23, 59, 59)
            return start, end

        monkeypatch.setattr(
            "app.handlers.exports.timelog_export.user_preferences_service.convert_date_range_to_timezone",
            fake_convert_range,
        )

        async def fake_search_events(*args, **kwargs):
            event = SimpleNamespace(
                start_time=datetime(2025, 6, 1, 9, 0, 0),
                end_time=datetime(2025, 6, 1, 10, 30, 0),
                dimension_id=None,
                title="Deep Work",
            )
            person_summary = {"display_name": "Bob"}
            task_summary = {
                "content": "Organize task list",
                "status": "done",
                "vision_summary": {"name": "Strategy Vision"},
            }
            setattr(event, "export_person_summaries", [person_summary])
            setattr(event, "export_task_summary", task_summary)
            return (
                [event],
                {
                    "limit": 1000,
                    "total_count": 1,
                    "returned_count": 1,
                    "truncated": False,
                },
            )

        monkeypatch.setattr(
            "app.handlers.exports.timelog_export._search_events_for_export",
            fake_search_events,
        )

        params = TimeLogExportParams(
            start_date=datetime(2025, 6, 1, 0, 0, 0),
            end_date=datetime(2025, 6, 1, 0, 0, 0),
        )

        export_text, metadata = await export_timelog_data(
            async_db_session, params=params, user_id=str(user.id)
        )

        assert "Organize task list" in export_text
        assert "Vision: Strategy Vision" in export_text
        assert "Status: Done" in export_text
        assert "Bob" in export_text
        assert "1h 30m" in export_text
        assert "Query Conditions:" in export_text
        assert metadata["returned_count"] == 1

    @pytest.mark.asyncio
    async def test_export_timelog_data_respects_user_timezone(
        self, async_db_session, monkeypatch
    ):
        user = User(
            id=uuid4(),
            email="timelog-tz@example.com",
            name="Time TZ User",
            password_hash="hashed",
        )
        async_db_session.add(user)
        await async_db_session.commit()
        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=user.id,
            key="system.language",
            value="en",
            module="system",
        )
        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=user.id,
            key="system.timezone",
            value="Asia/Shanghai",
            module="system",
        )

        async def fake_convert_range(*args, **kwargs):
            start = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
            end = datetime(2025, 6, 2, 0, 0, 0, tzinfo=timezone.utc)
            return start, end

        monkeypatch.setattr(
            "app.handlers.exports.timelog_export.user_preferences_service.convert_date_range_to_timezone",
            fake_convert_range,
        )

        async def fake_search_events(*args, **kwargs):
            event = SimpleNamespace(
                start_time=datetime(2025, 6, 1, 1, 0, 0, tzinfo=timezone.utc),
                end_time=datetime(2025, 6, 1, 2, 0, 0, tzinfo=timezone.utc),
                dimension_id=None,
                title="Focus Block",
            )
            return (
                [event],
                {
                    "limit": 1000,
                    "total_count": 1,
                    "returned_count": 1,
                    "truncated": False,
                },
            )

        monkeypatch.setattr(
            "app.handlers.exports.timelog_export._search_events_for_export",
            fake_search_events,
        )

        params = TimeLogExportParams(
            start_date=datetime(2025, 6, 1, 0, 0, 0),
            end_date=datetime(2025, 6, 1, 0, 0, 0),
        )

        export_text, metadata = await export_timelog_data(
            async_db_session, params=params, user_id=str(user.id)
        )

        assert "2025-06-01\t09:00\t10:00" in export_text
        assert "01:00" not in export_text
        assert metadata["total_count"] == 1

    @pytest.mark.asyncio
    async def test_export_timelog_data_returns_metadata_payload(
        self, async_db_session, monkeypatch
    ):
        user = User(
            id=uuid4(),
            email="timelog-meta@example.com",
            name="Time Meta User",
            password_hash="hashed",
        )
        async_db_session.add(user)
        await async_db_session.commit()
        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=user.id,
            key="system.language",
            value="en",
            module="system",
        )

        async def fake_convert_range(*args, **kwargs):
            start = datetime(2025, 7, 1, 0, 0, 0)
            end = datetime(2025, 7, 31, 23, 59, 59)
            return start, end

        monkeypatch.setattr(
            "app.handlers.exports.timelog_export.user_preferences_service.convert_date_range_to_timezone",
            fake_convert_range,
        )

        metadata_payload = {
            "limit": 1000,
            "total_count": 1500,
            "returned_count": 1000,
            "truncated": True,
        }

        async def fake_search_events(*args, **kwargs):
            return [], metadata_payload

        monkeypatch.setattr(
            "app.handlers.exports.timelog_export._search_events_for_export",
            fake_search_events,
        )

        params = TimeLogExportParams(
            start_date=datetime(2025, 7, 1, 0, 0, 0),
            end_date=datetime(2025, 7, 31, 0, 0, 0),
        )

        export_text, metadata = await export_timelog_data(
            async_db_session, params=params, user_id=str(user.id)
        )

        assert isinstance(export_text, str)
        assert metadata == metadata_payload

    def test_actual_event_snapshot_summary_contract(self):
        service = ActualEventExportService(locale="en")

        window_start = datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc)
        window_end = datetime(2025, 6, 1, 23, 59, tzinfo=timezone.utc)
        event_id = uuid4()
        dimension_id = uuid4()
        event = SimpleNamespace(
            id=event_id,
            start_time=window_start.replace(hour=9, minute=0),
            end_time=window_start.replace(hour=10, minute=30),
            dimension_id=dimension_id,
            title="Focus Work",
        )

        stats = service._calculate_statistics([event], None)
        summary_model = service.build_snapshot_summary(
            events=[event],
            stats=stats,
            start_dt=window_start,
            end_dt=window_end,
        )

        summary = summary_model.model_dump(mode="json", exclude_none=True)
        assert summary["total_records"] == 1
        assert summary["total_duration_minutes"] == 90
        assert summary["entry_ids"] == [str(event_id)]
        assert summary["date_range"]["start"].startswith("2025-06-01T00:00:00")
        assert summary["date_range"]["end"].startswith("2025-06-01T23:59:00")
        assert summary["dimension_stats"][0]["dimension_id"] == str(dimension_id)
        assert summary["dimension_stats"][0]["count"] == 1
        assert summary["dimension_stats"][0]["duration_minutes"] == 90

    def test_actual_event_snapshot_query_contract(self):
        filters = {
            "dimension_name": "Focus",
            "keyword": "meeting",
            "description_keyword": "retro",
            "tracking_method": "manual",
            "limit": "120",
        }

        query_model = ActualEventExportService.build_snapshot_query(filters)
        query = query_model.model_dump(exclude_none=True)

        assert query == {
            "dimension_name": "Focus",
            "keyword": "meeting",
            "description_keyword": "retro",
            "tracking_method": "manual",
            "limit": 120,
        }

    @pytest.mark.asyncio
    async def test_export_planning_data_respects_local_date(
        self, async_db_session, monkeypatch
    ):
        user = User(
            id=uuid4(),
            email="planning@example.com",
            name="Planning User",
            password_hash="hashed",
        )
        async_db_session.add(user)
        await async_db_session.commit()
        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=user.id,
            key="system.language",
            value="zh",
            module="system",
        )

        async def fake_timezone(*args, **kwargs):
            return "America/New_York"

        monkeypatch.setattr(
            "app.handlers.exports.planning_export.user_preferences_service.get_user_timezone",
            fake_timezone,
        )

        captured_args = {}

        async def fake_list_tasks(db, *, planning_cycle_start_date, **kwargs):
            captured_args["start_date"] = planning_cycle_start_date
            return []

        monkeypatch.setattr(
            "app.handlers.exports.planning_export.list_tasks", fake_list_tasks
        )

        params = PlanningExportParams(
            view_type="day",
            selected_date=datetime(2025, 10, 12, 15, 0, 0),
            include_notes=False,
        )

        export_text = await export_planning_data(
            async_db_session, params=params, user_id=str(user.id)
        )

        assert captured_args["start_date"] == "2025-10-12"
        assert "2025-10-12" in export_text

    @pytest.mark.asyncio
    async def test_export_planning_data_includes_related_task_notes(
        self, async_db_session
    ):
        user = User(
            id=uuid4(),
            email="planning-notes@example.com",
            name="Planning Notes User",
            password_hash="hashed",
        )
        vision = Vision(id=uuid4(), user_id=user.id, name="规划愿景")
        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="编写周报",
            status="todo",
            priority=0,
            display_order=0,
            planning_cycle_type="day",
            planning_cycle_start_date=datetime(2025, 10, 12).date(),
        )
        note = Note(id=uuid4(), user_id=user.id, content="完成周报草稿")
        association = Association(
            user_id=user.id,
            source_model=ModelName.Note,
            source_id=note.id,
            target_model=ModelName.Task,
            target_id=task.id,
            link_type=LinkType.RELATES_TO,
        )

        async_db_session.add(user)
        await async_db_session.commit()
        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=user.id,
            key="system.language",
            value="zh",
            module="system",
        )
        async_db_session.add_all([vision, task, note, association])
        await async_db_session.commit()

        params = PlanningExportParams(
            view_type="day",
            selected_date=datetime(2025, 10, 12, 9, 0, 0),
            include_notes=True,
        )

        export_text = await export_planning_data(
            async_db_session, params=params, user_id=str(user.id)
        )

        assert "编写周报" in export_text
        assert "相关任务: 编写周报" in export_text

    @pytest.mark.asyncio
    async def test_export_notes_data_includes_related_task(self, async_db_session):
        user = User(
            id=uuid4(),
            email="notes-task@example.com",
            name="Notes Task User",
            password_hash="hashed",
        )
        vision = Vision(id=uuid4(), user_id=user.id, name="记录愿景")
        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="整理会议纪要",
            status="todo",
            priority=0,
            display_order=0,
        )
        note = Note(id=uuid4(), user_id=user.id, content="会议纪要内容")
        association = Association(
            user_id=user.id,
            source_model=ModelName.Note,
            source_id=note.id,
            target_model=ModelName.Task,
            target_id=task.id,
            link_type=LinkType.RELATES_TO,
        )
        async_db_session.add(user)
        await async_db_session.commit()
        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=user.id,
            key="system.language",
            value="zh",
            module="system",
        )
        async_db_session.add_all([vision, task, note, association])
        await async_db_session.commit()

        params = NotesExportParams(
            selected_filter_tags=[],
            selected_filter_persons=[],
        )

        export_text = await export_notes_data(
            async_db_session, params=params, user_id=str(user.id)
        )

        assert "相关任务: 整理会议纪要" in export_text

    @pytest.mark.asyncio
    async def test_export_vision_data_includes_time_records(self, async_db_session):
        user = User(
            id=uuid4(),
            email="vision@example.com",
            name="Vision User",
            password_hash="hashed",
        )
        vision = Vision(id=uuid4(), user_id=user.id, name="愿景 A")
        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="撰写总结",
            status="todo",
            priority=0,
            display_order=0,
        )
        event = ActualEvent(
            id=uuid4(),
            user_id=user.id,
            title="整理资料",
            start_time=datetime(2025, 7, 1, 8, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2025, 7, 1, 9, 0, 0, tzinfo=timezone.utc),
            task_id=task.id,
        )

        async_db_session.add_all([user, vision, task, event])
        await async_db_session.commit()
        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=user.id,
            key="system.language",
            value="zh",
            module="system",
        )

        params = VisionExportParams(
            include_subtasks=True,
            include_notes=False,
            include_time_records=True,
        )

        export_text = await export_vision_data(
            async_db_session,
            params=params,
            user_id=str(user.id),
            vision_id=str(vision.id),
        )

        assert "撰写总结" in export_text
        assert "记录: 1小时" in export_text

    def test_vision_export_handles_task_cycle(self):
        params = VisionExportParams(
            include_subtasks=True,
            include_notes=False,
            include_time_records=False,
        )
        service = VisionExportService(locale="zh-CN")

        class TaskStub:
            def __init__(self, identifier, content):
                self.id = identifier
                self.content = content
                self.status = "todo"
                self.priority = 0
                self.subtasks: list["TaskStub"] = []
                self.actual_effort_total = 0
                self.estimated_effort = None
                self.persons: list = []

        root = TaskStub(uuid4(), "根任务")
        child = TaskStub(uuid4(), "子任务")
        root.subtasks = [child]
        child.subtasks = [root]

        lines = service._create_task_tree_section([root], params)

        root_count = sum(1 for line in lines if line.rstrip().endswith("根任务"))
        child_count = sum(1 for line in lines if line.rstrip().endswith("子任务"))

        assert root_count == 1
        assert child_count == 1
