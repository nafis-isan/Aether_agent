from typing import Sequence, Union

from alembic import op

revision: str = "20261030_0002"
down_revision: Union[str, None] = "20261030_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE messages MODIFY created_at DATETIME(6) "
        "NOT NULL DEFAULT CURRENT_TIMESTAMP(6)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE messages MODIFY created_at DATETIME "
        "NOT NULL DEFAULT CURRENT_TIMESTAMP"
    )
