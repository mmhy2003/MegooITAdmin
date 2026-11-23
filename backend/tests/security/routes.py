"""Reads the audit declarations, the session requirement and the access requirement of an app's routes, for the
audit-, auth- and permission-coverage suites.

Since FastAPI 0.165, include_router keeps the router as one node in app.routes instead of copying its routes.
iter_route_contexts, which FastAPI's OpenAPI generator uses too, yields every route as it is served: the full
path, and the dependencies of the route and of every router it was included through."""

from collections.abc import Callable, Iterator, Mapping
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_parameterless_sub_dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from starlette.routing import Route

from app.auth.deps import current_session, current_user

STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
READ_ONLY = frozenset({"GET", "HEAD"})


def api_routes(app: FastAPI) -> list[RouteContext]:
    """Every APIRoute of the app, with its full path and all its dependencies."""
    return [context for context in iter_route_contexts(app.routes) if isinstance(context.original_route, APIRoute)]


def declared_actions(route: APIRoute | RouteContext) -> frozenset[str]:
    """The actions named by the route's audited(...) dependencies."""
    return frozenset().union(*(getattr(dep.dependency, "audit_actions", frozenset()) for dep in route.dependencies))


def unaudited_routes(app: FastAPI, exempt: Mapping[str, str]) -> list[str]:
    """'METHOD /path' of every state-changing route that declares no action and is not exempt, sorted."""
    return sorted(
        name
        for route in api_routes(app)
        if not declared_actions(route)
        for method in route.methods & STATE_CHANGING
        if (name := f"{method} {route.path}") not in exempt
    )


def unknown_routes(app: FastAPI) -> list[str]:
    """Routes the check cannot see into: anything but an APIRoute or a read-only starlette Route (the docs)."""
    return [
        f"{type(route).__name__} {context.path or '?'}"
        for context in iter_route_contexts(app.routes)
        if not isinstance(route := context.original_route, APIRoute)
        and not (isinstance(route, Route) and route.methods is not None and route.methods <= READ_ONLY)
    ]


def _calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for sub in dependant.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from _calls(sub)


def dependency_calls(context: RouteContext) -> set[Callable[..., Any]]:
    """Every dependency the route runs: its own, nested ones, and those of the routers it was included through."""
    calls = set(_calls(context.original_route.dependant))
    for dep in context.dependencies:
        if dep.dependency is not None:
            calls.add(dep.dependency)
            # As FastAPI builds it, keeping the dependency's scope: audited(...) has scope="function".
            calls.update(_calls(get_parameterless_sub_dependant(depends=dep, path=context.path)))
    return calls


def session_requirement(context: RouteContext) -> Literal["active", "pending", "none"]:
    calls = dependency_calls(context)
    if current_user in calls:
        return "active"
    if current_session in calls:
        return "pending"
    return "none"


def unguarded_routes(app: FastAPI, public: Mapping[str, str], pending: Mapping[str, str]) -> list[str]:
    """'METHOD /path (requirement)' of every route that works without an active session and is not pinned in the
    list for its requirement, sorted."""
    pinned = {"none": public, "pending": pending}
    return sorted(
        f"{name} ({requirement})"
        for context in api_routes(app)
        if (requirement := session_requirement(context)) != "active"
        for method in context.methods
        if (name := f"{method} {context.path}") not in pinned[requirement]
    )


def access_requirement(context: RouteContext) -> str | None:
    """What the route's access guard requires ('owner', a permission, 'group', 'admin'), or None when it has no
    guard. require_owner, require_grant(...), require_group_visible(...) and require_group_admin(...) carry it as an
    `access_requirement` attribute."""
    requirements = (getattr(call, "access_requirement", None) for call in dependency_calls(context))
    return min((requirement for requirement in requirements if requirement), default=None)


def undeclared_routes(app: FastAPI, any_signed_in: Mapping[str, str]) -> list[str]:
    """'METHOD /path' of every route that needs an active session, has no access guard and is not pinned, sorted."""
    return sorted(
        name
        for context in api_routes(app)
        if session_requirement(context) == "active" and access_requirement(context) is None
        for method in context.methods
        if (name := f"{method} {context.path}") not in any_signed_in
    )
