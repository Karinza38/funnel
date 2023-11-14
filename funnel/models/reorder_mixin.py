"""Mixin class to support reordering in any model with a container model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, TypeVar
from uuid import UUID

from . import Mapped, QueryProperty, db, declarative_mixin, sa

__all__ = ['ReorderProtoMixin']


# Use of TypeVar for subclasses of ReorderMixin as defined in these mypy tickets:
# https://github.com/python/mypy/issues/1212
# https://github.com/python/mypy/issues/7191
Reorderable = TypeVar('Reorderable', bound='ReorderProtoMixin')


@declarative_mixin
class ReorderProtoMixin:
    """Adds support for re-ordering sequences within a parent container."""

    if TYPE_CHECKING:
        #: Subclasses must have a created_at column
        created_at: Mapped[datetime]
        #: Subclass must have a primary key that is int or uuid
        id: Mapped[int | UUID]  # noqa: A001
        #: Subclass must declare a parent_id synonym to the parent model fkey column
        parent_id: Mapped[int | UUID]
        #: Subclass must declare a seq column or synonym, holding a sequence id. It
        #: need not be unique, but reordering is meaningless when both items have the
        #: same number
        seq: Mapped[int]

        #: Subclass must offer a SQLAlchemy query (this is standard from base classes)
        query: ClassVar[QueryProperty]

    @property
    def parent_scoped_reorder_query_filter(self: Reorderable) -> sa.ColumnElement[bool]:
        """
        Return a query filter that includes a scope limitation to the parent.

        Used alongside the :attr:`seq` column to retrieve a sequence value. Subclasses
        may need to override if they have additional criteria relative to the parent,
        such as needing to exclude revoked membership records.
        """
        cls = self.__class__
        return cls.parent_id == self.parent_id

    def reorder_item(self: Reorderable, other: Reorderable, before: bool) -> None:
        """Reorder self before or after other item."""
        cls = self.__class__

        # Safety checks
        if other.__class__ is not cls:
            raise TypeError("Other must be of the same type")
        if other.parent_id != self.parent_id:
            raise ValueError("Other must have the same parent")
        if self.seq is None or other.seq is None:
            raise ValueError("Sequence numbers must be pre-assigned to reorder")

        if before:
            if self.seq <= other.seq:
                # We're already before or equal. Nothing to do.
                return
            order_columns = (cls.seq.desc(), cls.created_at.desc())
        else:
            if self.seq >= other.seq:
                # We're already after or equal. Nothing to do.
                return
            order_columns = (cls.seq.asc(), cls.created_at.asc())

        # Get all sequence numbers between self and other inclusive. Use:
        # descending order if moving up (before other),
        # ascending order if moving down (after other)

        items_to_reorder = (
            cls.query.filter(
                self.parent_scoped_reorder_query_filter,
                cls.seq >= min(self.seq, other.seq),
                cls.seq <= max(self.seq, other.seq),
            )
            .with_for_update(of=cls)  # Lock these rows to prevent a parallel update
            .options(sa.orm.load_only(cls.id, cls.seq))
            .order_by(*order_columns)
            .all()
        )

        # Pop-off items that share a sequence number and don't need to be moved
        while items_to_reorder[0].id != self.id:
            items_to_reorder.pop(0)

        # Reordering! Move down the list (reversed if `before`), reassigning numbers.
        # This list will always start with `self` and end with `other` (with a possible
        # tail of items that share the same sequence number as `other`). We assign
        # self's sequence number to the next item in the list, and that one's to the
        # next and so on until we reach `other`. Then we assign other's sequence
        # number to self and we're done.

        new_seq_number = self.seq
        # Temporarily give self an out-of-bounds number
        self.seq = (
            sa.select(  # type: ignore[assignment]
                sa.func.coalesce(sa.func.max(cls.seq) + 1, 1)
            )
            .where(self.parent_scoped_reorder_query_filter)
            .scalar_subquery()
        )
        # Flush it so the db doesn't complain when there's a unique constraint
        db.session.flush()
        # Reassign all remaining sequence numbers
        for reorderable_item in items_to_reorder[1:]:  # Skip 0, which is self
            reorderable_item.seq, new_seq_number = new_seq_number, reorderable_item.seq
            # Flush to force execution order. This does not expunge SQLAlchemy cache as
            # of SQLAlchemy 2.0.x. Should that behaviour change, a switch to
            # bulk_update_mappings will be required
            db.session.flush()
            if reorderable_item.id == other.id:
                # Don't bother reordering anything after `other`
                break
        # Assign other's previous sequence number to self
        self.seq = new_seq_number
        db.session.flush()

    def reorder_before(self: Reorderable, other: Reorderable) -> None:
        """Reorder to be before another item's sequence number."""
        self.reorder_item(other, True)

    def reorder_after(self: Reorderable, other: Reorderable) -> None:
        """Reorder to be after another item's sequence number."""
        self.reorder_item(other, False)
