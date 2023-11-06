"""Notification helpers and mixins."""

from collections.abc import Callable
from typing import Generic, Self, TypeVar, overload

import grapheme

from ...models import Account, Project

_T = TypeVar('_T')  # Host type for SetVar
_I = TypeVar('_I')  # Input type for SetVar's setter
_O = TypeVar('_O')  # Output type for SetVar's setter


class SetVar(Generic[_T, _I, _O]):
    """Decorator for template variable setters."""

    name: str

    def __init__(self, fset: Callable[[_T, _I], _O]) -> None:
        self.fset = fset

    def __set_name__(self, owner: type[_T], name: str) -> None:
        if getattr(self, 'name', None) is None:
            self.name = name
        else:
            # We're getting cloned, so make a copy in the owner
            copy = SetVar(self.fset)
            setattr(owner, name, copy)
            copy.__set_name__(owner, name)

    @overload
    def __get__(self, instance: None, owner: type[_T]) -> Self:
        ...

    @overload
    def __get__(self, instance: _T, owner: None = None) -> _O:
        ...

    @overload
    def __get__(self, instance: _T, owner: type[_T]) -> _O:
        ...

    def __get__(self, instance: _T | None, owner: type[_T] | None = None) -> Self | _O:
        if instance is None:
            return self
        try:
            return instance.__dict__[self.name]
        except KeyError:
            raise AttributeError(self.name) from None

    def __set__(self, instance: _T, value: _I) -> None:
        instance.__dict__[self.name] = self.fset(instance, value)

    def __delete__(self, instance: _T) -> None:
        try:
            instance.__dict__.pop(self.name)
        except KeyError:
            raise AttributeError(self.name) from None


class TemplateVarMixin:
    """Mixin class for common variables in SMS templates."""

    var_max_length: int

    @SetVar
    def project(self, project: Project) -> str:
        """Set project joined title or title, truncated to fit the length limit."""
        if len(project.joined_title) <= self.var_max_length:
            return project.joined_title
        title = project.title
        if len(title) <= self.var_max_length:
            return title
        index = grapheme.safe_split_index(title, self.var_max_length - 1)
        return title[:index] + '…'

    @SetVar
    def account(self, account: Account) -> str:
        """Set account's display name, truncated to fit."""
        pickername = account.pickername
        if len(pickername) <= self.var_max_length:
            return pickername
        title = account.title
        if len(title) <= self.var_max_length:
            return title
        index = grapheme.safe_split_index(title, self.var_max_length - 1)
        return title[:index] + '…'

    # This will trigger cloning in SetVar.__set_name__
    actor = user = organization = profile = account
