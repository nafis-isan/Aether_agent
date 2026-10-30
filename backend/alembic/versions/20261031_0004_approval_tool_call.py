from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261031_0004"
down_revision: Union[str, None] = "20261031_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "approvals",
        sa.Column("tool_call_id", sa.String(length=120), nullable=False, server_default=""),
    )
    op.alter_column("approvals", "tool_call_id", server_default=None)


def downgrade() -> None:
    op.drop_column("approvals", "tool_call_id")
