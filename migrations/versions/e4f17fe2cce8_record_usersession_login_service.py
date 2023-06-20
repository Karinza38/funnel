"""Record UserSession.login_service.

Revision ID: e4f17fe2cce8
Revises: b6d0edac3e20
Create Date: 2020-07-19 05:04:51.004750

"""

from typing import Optional, Tuple, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e4f17fe2cce8'
down_revision = 'b6d0edac3e20'
branch_labels: Optional[Union[str, Tuple[str, ...]]] = None
depends_on: Optional[Union[str, Tuple[str, ...]]] = None


def upgrade() -> None:
    op.add_column(
        'user_session', sa.Column('login_service', sa.Unicode(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('user_session', 'login_service')
