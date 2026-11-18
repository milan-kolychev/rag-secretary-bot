"""Initial persistent chat, queue and version metadata (no existing migrations)."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("chat_id", sa.BigInteger, nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_chat_messages_chat_id", "chat_messages", ["chat_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])
    op.create_table(
        "request_jobs",
        sa.Column("sequence", sa.Integer, primary_key=True),
        sa.Column("id", sa.String(36), nullable=False, unique=True),
        sa.Column("chat_id", sa.BigInteger, nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("busy", sa.Boolean, nullable=False),
        sa.Column("acknowledged", sa.Boolean, nullable=False),
        sa.Column("result", sa.JSON),
        sa.Column("error", sa.String(32)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
    )
    op.create_index("ix_request_jobs_state", "request_jobs", ["state"])
    op.create_index(
        "uq_request_jobs_busy",
        "request_jobs",
        ["chat_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("busy"),
        sqlite_where=sa.text("busy = 1"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("active_version", sa.Integer),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("doc_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("chunks", sa.Integer),
        sa.Column("error", sa.String(64)),
        sa.Column("uploaded_at", sa.DateTime, nullable=False),
        sa.Column("indexed_at", sa.DateTime),
        sa.UniqueConstraint("doc_id", "version"),
        sa.UniqueConstraint("doc_id", "checksum"),
    )
    op.create_index("ix_document_versions_doc_id", "document_versions", ["doc_id"])


def downgrade():
    for table in ("document_versions", "documents", "request_jobs", "chat_messages"):
        op.drop_table(table)
