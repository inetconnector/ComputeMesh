"""ComputeMesh Gateway Service."""

__all__ = ["GatewayHandler", "run_gateway_server"]


def __getattr__(name: str):
    if name in __all__:
        from services.gateway.server import GatewayHandler, run_gateway_server

        return {"GatewayHandler": GatewayHandler, "run_gateway_server": run_gateway_server}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
