"""Reads the audit declarations of an app's routes, for the audit-coverage suite.

Since FastAPI 0.165, include_router keeps the router as one node in app.routes instead of copying its routes.
iter_route_contexts, which FastAPI's OpenAPI generator uses too, yields every route as it is served: the full
path, and the dependencies of the route and of every router it was included through."""

from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from starlette.routing import Route

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
