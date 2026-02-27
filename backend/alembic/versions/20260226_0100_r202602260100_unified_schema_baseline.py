"""unified schema baseline

Revision ID: r202602260100
Revises:
Create Date: 2026-02-26 01:00:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "r202602260100"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")

SCHEMA_TOKEN = "__SCHEMA__"


CREATE_ENUM_STATEMENTS = [
    "CREATE TYPE __SCHEMA__.invitation_status AS ENUM ('PENDING', 'REGISTERED', 'REVOKED', 'EXPIRED')",
]


CREATE_STATEMENTS = [
    "CREATE TABLE __SCHEMA__.a2a_proxy_allowlist (\n\thost_pattern VARCHAR(255) NOT NULL, \n\tis_enabled BOOLEAN NOT NULL, \n\tremark TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id)\n)",
    "CREATE UNIQUE INDEX ix___SCHEMA___a2a_proxy_allowlist_host_pattern ON __SCHEMA__.a2a_proxy_allowlist (host_pattern)",
    "CREATE INDEX ix___SCHEMA___a2a_proxy_allowlist_is_enabled ON __SCHEMA__.a2a_proxy_allowlist (is_enabled)",
    "CREATE TABLE __SCHEMA__.users (\n\temail VARCHAR(255) NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tpassword_hash VARCHAR(255) NOT NULL, \n\ttimezone VARCHAR(64) DEFAULT 'UTC' NOT NULL, \n\tis_superuser BOOLEAN NOT NULL, \n\tdisabled_at TIMESTAMP WITH TIME ZONE, \n\tfailed_login_attempts INTEGER DEFAULT '0' NOT NULL, \n\tlocked_until TIMESTAMP WITH TIME ZONE, \n\tlast_login_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id)\n)",
    "CREATE UNIQUE INDEX ix___SCHEMA___users_email ON __SCHEMA__.users (email)",
    "CREATE TABLE __SCHEMA__.a2a_agents (\n\tname VARCHAR(120) NOT NULL, \n\tcard_url VARCHAR(1024) NOT NULL, \n\tagent_scope VARCHAR(16) DEFAULT 'personal' NOT NULL, \n\tavailability_policy VARCHAR(32) DEFAULT 'public' NOT NULL, \n\tauth_type VARCHAR(32) DEFAULT 'none' NOT NULL, \n\tauth_header VARCHAR(120), \n\tauth_scheme VARCHAR(64), \n\tenabled BOOLEAN DEFAULT 'true' NOT NULL, \n\ttags JSON, \n\textra_headers JSON, \n\tcreated_by_user_id UUID, \n\tupdated_by_user_id UUID, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\tuser_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_a2a_agents_user_scope_card_url UNIQUE (user_id, agent_scope, card_url), \n\tFOREIGN KEY(created_by_user_id) REFERENCES __SCHEMA__.users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(updated_by_user_id) REFERENCES __SCHEMA__.users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix___SCHEMA___a2a_agents_user_id ON __SCHEMA__.a2a_agents (user_id)",
    "CREATE TABLE __SCHEMA__.conversation_threads (\n\tagent_id UUID, \n\tagent_source VARCHAR(16), \n\tsource VARCHAR(16) DEFAULT 'manual' NOT NULL, \n\texternal_provider VARCHAR(64), \n\texternal_session_id VARCHAR(255), \n\tcontext_id VARCHAR(255), \n\ttitle VARCHAR(255) NOT NULL, \n\tlast_active_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstatus VARCHAR(16) DEFAULT 'active' NOT NULL, \n\tmerged_into_id UUID, \n\tnotes TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tuser_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_conversation_threads_user_provider_external_session UNIQUE (user_id, external_provider, external_session_id), \n\tCONSTRAINT ck_conversation_threads_source_allowed_values CHECK (source IN ('manual', 'scheduled')), \n\tCONSTRAINT ck_conversation_threads_external_session_requires_provider CHECK ((external_session_id IS NULL) OR (external_provider IS NOT NULL)), \n\tFOREIGN KEY(merged_into_id) REFERENCES __SCHEMA__.conversation_threads (id) ON DELETE SET NULL, \n\tFOREIGN KEY(user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix___SCHEMA___conversation_threads_agent_id ON __SCHEMA__.conversation_threads (agent_id)",
    "CREATE INDEX ix___SCHEMA___conversation_threads_context_id ON __SCHEMA__.conversation_threads (context_id)",
    "CREATE INDEX ix___SCHEMA___conversation_threads_external_provider ON __SCHEMA__.conversation_threads (external_provider)",
    "CREATE INDEX ix___SCHEMA___conversation_threads_external__f921 ON __SCHEMA__.conversation_threads (external_session_id)",
    "CREATE INDEX ix___SCHEMA___conversation_threads_last_active_at ON __SCHEMA__.conversation_threads (last_active_at)",
    "CREATE INDEX ix___SCHEMA___conversation_threads_user_id ON __SCHEMA__.conversation_threads (user_id)",
    "CREATE INDEX ix_conversation_threads_user_id_updated_at ON __SCHEMA__.conversation_threads (user_id, updated_at)",
    "CREATE TABLE __SCHEMA__.external_session_directory_cache (\n\tuser_id UUID NOT NULL, \n\tprovider VARCHAR(32) NOT NULL, \n\tagent_source VARCHAR(16) NOT NULL, \n\tagent_id UUID NOT NULL, \n\tpayload JSON NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_success_at TIMESTAMP WITH TIME ZONE, \n\tlast_error_code VARCHAR(64), \n\tlast_error_at TIMESTAMP WITH TIME ZONE, \n\trefreshed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_external_session_directory_cache_user_provider_source_agent UNIQUE (user_id, provider, agent_source, agent_id), \n\tFOREIGN KEY(user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix___SCHEMA___external_session_directory_cac_a141 ON __SCHEMA__.external_session_directory_cache (agent_id)",
    "CREATE INDEX ix___SCHEMA___external_session_directory_cac_e1ca ON __SCHEMA__.external_session_directory_cache (expires_at)",
    "CREATE INDEX ix___SCHEMA___external_session_directory_cac_b56b ON __SCHEMA__.external_session_directory_cache (provider)",
    "CREATE INDEX ix___SCHEMA___external_session_directory_cac_9944 ON __SCHEMA__.external_session_directory_cache (user_id)",
    "CREATE TABLE __SCHEMA__.invitations (\n\tcode VARCHAR(64) NOT NULL, \n\tcreator_user_id UUID NOT NULL, \n\ttarget_email VARCHAR(255) NOT NULL, \n\tstatus __SCHEMA__.invitation_status NOT NULL, \n\ttarget_user_id UUID, \n\tregistered_at TIMESTAMP WITH TIME ZONE, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\texpires_at TIMESTAMP WITH TIME ZONE, \n\tmemo TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_invitations_creator_email UNIQUE (creator_user_id, target_email), \n\tUNIQUE (code), \n\tFOREIGN KEY(creator_user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE, \n\tFOREIGN KEY(target_user_id) REFERENCES __SCHEMA__.users (id) ON DELETE SET NULL\n)",
    "CREATE INDEX ix___SCHEMA___invitations_creator_user_id ON __SCHEMA__.invitations (creator_user_id)",
    "CREATE INDEX ix___SCHEMA___invitations_target_email ON __SCHEMA__.invitations (target_email)",
    "CREATE TABLE __SCHEMA__.ws_tickets (\n\tscope_type VARCHAR(32), \n\tagent_id UUID NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tused_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tuser_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (token_hash), \n\tFOREIGN KEY(user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix___SCHEMA___ws_tickets_agent_id ON __SCHEMA__.ws_tickets (agent_id)",
    "CREATE INDEX ix___SCHEMA___ws_tickets_scope_type ON __SCHEMA__.ws_tickets (scope_type)",
    "CREATE INDEX ix___SCHEMA___ws_tickets_user_id ON __SCHEMA__.ws_tickets (user_id)",
    "CREATE INDEX ix_ws_tickets_expires_at ON __SCHEMA__.ws_tickets (expires_at)",
    "CREATE TABLE __SCHEMA__.a2a_agent_credentials (\n\tagent_id UUID NOT NULL, \n\tcreated_by_user_id UUID, \n\tencrypted_token TEXT NOT NULL, \n\ttoken_last4 VARCHAR(12), \n\tencryption_version INTEGER DEFAULT '1' NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_a2a_agent_credentials_agent UNIQUE (agent_id), \n\tFOREIGN KEY(agent_id) REFERENCES __SCHEMA__.a2a_agents (id) ON DELETE CASCADE, \n\tFOREIGN KEY(created_by_user_id) REFERENCES __SCHEMA__.users (id) ON DELETE RESTRICT\n)",
    "CREATE INDEX ix___SCHEMA___a2a_agent_credentials_agent_id ON __SCHEMA__.a2a_agent_credentials (agent_id)",
    "CREATE TABLE __SCHEMA__.a2a_schedule_tasks (\n\tname VARCHAR(120) NOT NULL, \n\tagent_id UUID NOT NULL, \n\tconversation_id UUID, \n\tconversation_policy VARCHAR(32) DEFAULT 'new_each_run' NOT NULL, \n\tprompt TEXT NOT NULL, \n\tcycle_type VARCHAR(16) NOT NULL, \n\ttime_point JSONB NOT NULL, \n\tenabled BOOLEAN DEFAULT 'true' NOT NULL, \n\tnext_run_at TIMESTAMP WITH TIME ZONE, \n\tconsecutive_failures INTEGER DEFAULT '0' NOT NULL, \n\tlast_run_at TIMESTAMP WITH TIME ZONE, \n\tlast_run_status VARCHAR(32) DEFAULT 'idle' NOT NULL, \n\tcurrent_run_id UUID, \n\trunning_started_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\tuser_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(agent_id) REFERENCES __SCHEMA__.a2a_agents (id) ON DELETE CASCADE, \n\tFOREIGN KEY(conversation_id) REFERENCES __SCHEMA__.conversation_threads (id) ON DELETE SET NULL, \n\tFOREIGN KEY(user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix___SCHEMA___a2a_schedule_tasks_agent_id ON __SCHEMA__.a2a_schedule_tasks (agent_id)",
    "CREATE INDEX ix___SCHEMA___a2a_schedule_tasks_conversation_id ON __SCHEMA__.a2a_schedule_tasks (conversation_id)",
    "CREATE INDEX ix___SCHEMA___a2a_schedule_tasks_next_run_at ON __SCHEMA__.a2a_schedule_tasks (next_run_at)",
    "CREATE INDEX ix___SCHEMA___a2a_schedule_tasks_user_id ON __SCHEMA__.a2a_schedule_tasks (user_id)",
    "CREATE INDEX ix_a2a_schedule_tasks_due ON __SCHEMA__.a2a_schedule_tasks (user_id, enabled, next_run_at)",
    "CREATE INDEX ix_a2a_schedule_tasks_user_id_created_at ON __SCHEMA__.a2a_schedule_tasks (user_id, created_at)",
    "CREATE TABLE __SCHEMA__.agent_messages (\n\tconversation_id UUID NOT NULL, \n\tstatus VARCHAR(24) DEFAULT 'done' NOT NULL, \n\tfinish_reason VARCHAR(64), \n\terror_code VARCHAR(64), \n\tsender VARCHAR(16) NOT NULL, \n\tmetadata JSONB, \n\tinvoke_idempotency_key VARCHAR(160), \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tuser_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(conversation_id) REFERENCES __SCHEMA__.conversation_threads (id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix___SCHEMA___agent_messages_conversation_id ON __SCHEMA__.agent_messages (conversation_id)",
    "CREATE INDEX ix___SCHEMA___agent_messages_user_id ON __SCHEMA__.agent_messages (user_id)",
    "CREATE INDEX ix_agent_messages_conversation_id_created_at ON __SCHEMA__.agent_messages (conversation_id, created_at)",
    "CREATE UNIQUE INDEX uq_agent_messages_conversation_sender_invoke_idempotency_key ON __SCHEMA__.agent_messages (conversation_id, sender, invoke_idempotency_key) WHERE invoke_idempotency_key IS NOT NULL AND sender IN ('user', 'agent')",
    "CREATE TABLE __SCHEMA__.hub_a2a_agent_allowlist (\n\tagent_id UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\tcreated_by_user_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_hub_a2a_agent_allowlist_agent_user UNIQUE (agent_id, user_id), \n\tFOREIGN KEY(agent_id) REFERENCES __SCHEMA__.a2a_agents (id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE, \n\tFOREIGN KEY(created_by_user_id) REFERENCES __SCHEMA__.users (id) ON DELETE RESTRICT\n)",
    "CREATE INDEX ix___SCHEMA___hub_a2a_agent_allowlist_agent_id ON __SCHEMA__.hub_a2a_agent_allowlist (agent_id)",
    "CREATE INDEX ix___SCHEMA___hub_a2a_agent_allowlist_user_id ON __SCHEMA__.hub_a2a_agent_allowlist (user_id)",
    "CREATE TABLE __SCHEMA__.user_shortcuts (\n\ttitle VARCHAR(120) NOT NULL, \n\tprompt TEXT NOT NULL, \n\tis_default BOOLEAN DEFAULT 'false' NOT NULL, \n\tsort_order INTEGER DEFAULT '0' NOT NULL, \n\tagent_id UUID, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tuser_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(agent_id) REFERENCES __SCHEMA__.a2a_agents (id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix___SCHEMA___user_shortcuts_user_id ON __SCHEMA__.user_shortcuts (user_id)",
    "CREATE INDEX ix_user_shortcuts_agent_id ON __SCHEMA__.user_shortcuts (agent_id)",
    "CREATE INDEX ix_user_shortcuts_user_id ON __SCHEMA__.user_shortcuts (user_id)",
    "CREATE INDEX ix_user_shortcuts_user_sort_order ON __SCHEMA__.user_shortcuts (user_id, sort_order)",
    "CREATE TABLE __SCHEMA__.a2a_schedule_executions (\n\ttask_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tscheduled_for TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tstatus VARCHAR(32) DEFAULT 'running' NOT NULL, \n\terror_message TEXT, \n\tresponse_content TEXT, \n\tconversation_id UUID, \n\tuser_message_id UUID, \n\tagent_message_id UUID, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tuser_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_a2a_schedule_executions_task_run UNIQUE (task_id, run_id), \n\tFOREIGN KEY(task_id) REFERENCES __SCHEMA__.a2a_schedule_tasks (id) ON DELETE CASCADE, \n\tFOREIGN KEY(conversation_id) REFERENCES __SCHEMA__.conversation_threads (id) ON DELETE SET NULL, \n\tFOREIGN KEY(user_message_id) REFERENCES __SCHEMA__.agent_messages (id) ON DELETE SET NULL, \n\tFOREIGN KEY(agent_message_id) REFERENCES __SCHEMA__.agent_messages (id) ON DELETE SET NULL, \n\tFOREIGN KEY(user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix___SCHEMA___a2a_schedule_executions_agent__16e3 ON __SCHEMA__.a2a_schedule_executions (agent_message_id)",
    "CREATE INDEX ix___SCHEMA___a2a_schedule_executions_conver_3966 ON __SCHEMA__.a2a_schedule_executions (conversation_id)",
    "CREATE INDEX ix___SCHEMA___a2a_schedule_executions_run_id ON __SCHEMA__.a2a_schedule_executions (run_id)",
    "CREATE INDEX ix___SCHEMA___a2a_schedule_executions_task_id ON __SCHEMA__.a2a_schedule_executions (task_id)",
    "CREATE INDEX ix___SCHEMA___a2a_schedule_executions_user_id ON __SCHEMA__.a2a_schedule_executions (user_id)",
    "CREATE INDEX ix___SCHEMA___a2a_schedule_executions_user_m_6e4c ON __SCHEMA__.a2a_schedule_executions (user_message_id)",
    "CREATE INDEX ix_a2a_schedule_executions_task_created ON __SCHEMA__.a2a_schedule_executions (task_id, created_at)",
    "CREATE TABLE __SCHEMA__.agent_message_blocks (\n\tmessage_id UUID NOT NULL, \n\tblock_seq INTEGER NOT NULL, \n\tblock_type VARCHAR(32) NOT NULL, \n\tcontent TEXT NOT NULL, \n\tis_finished BOOLEAN DEFAULT false NOT NULL, \n\tsource VARCHAR(64), \n\tstart_event_seq INTEGER, \n\tend_event_seq INTEGER, \n\tstart_event_id VARCHAR(128), \n\tend_event_id VARCHAR(128), \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tuser_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(message_id) REFERENCES __SCHEMA__.agent_messages (id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id) REFERENCES __SCHEMA__.users (id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix___SCHEMA___agent_message_blocks_message_id ON __SCHEMA__.agent_message_blocks (message_id)",
    "CREATE INDEX ix___SCHEMA___agent_message_blocks_user_id ON __SCHEMA__.agent_message_blocks (user_id)",
    "CREATE UNIQUE INDEX ix_agent_message_blocks_message_id_block_seq ON __SCHEMA__.agent_message_blocks (message_id, block_seq)",
]


DROP_STATEMENTS = [
    'DROP TABLE IF EXISTS "__SCHEMA__"."agent_message_blocks" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."a2a_schedule_executions" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."user_shortcuts" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."hub_a2a_agent_allowlist" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."agent_messages" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."a2a_schedule_tasks" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."a2a_agent_credentials" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."ws_tickets" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."invitations" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."external_session_directory_cache" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."conversation_threads" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."a2a_agents" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."users" CASCADE',
    'DROP TABLE IF EXISTS "__SCHEMA__"."a2a_proxy_allowlist" CASCADE',
]

DROP_ENUM_STATEMENTS = [
    'DROP TYPE IF EXISTS "__SCHEMA__"."invitation_status" CASCADE',
]


def _materialize_schema(stmt: str) -> str:
    return stmt.replace(SCHEMA_TOKEN, SCHEMA_NAME)


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}"))
    for stmt in CREATE_ENUM_STATEMENTS:
        op.execute(sa.text(_materialize_schema(stmt)))
    for stmt in CREATE_STATEMENTS:
        op.execute(sa.text(_materialize_schema(stmt)))


def downgrade() -> None:
    for stmt in DROP_STATEMENTS:
        op.execute(sa.text(_materialize_schema(stmt)))
    for stmt in DROP_ENUM_STATEMENTS:
        op.execute(sa.text(_materialize_schema(stmt)))
