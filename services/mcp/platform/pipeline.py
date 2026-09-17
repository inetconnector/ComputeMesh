"""Composable orchestration pipeline joining request analysis, routing and DAG execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from .contracts import RequestEnvelope, RoutingDecision, SideEffectLevel
from .request_analysis import RequestAnalysis, RequestAnalyzer
from .reroute import RerouteManager, RerouteResult
from .skill_registry import PersistentSkillRegistry
from .skill_router import SkillRouter
from .validation import PlatformError, ValidationEngine
from .workflow import DAGWorkflowEngine, WorkflowNode, WorkflowResult


@dataclass(frozen=True)
class PlannedTask:
    task_id: str
    description: str
    skill_id: str
    dependencies: tuple[str, ...]
    expected_output: str
    validation: tuple[str, ...]
    failure_policy: str
    parallelizable: bool
    side_effect: str
    status: str = "PENDING"


@dataclass(frozen=True)
class OrchestrationPlan:
    request: RequestEnvelope
    analysis: RequestAnalysis
    routing: RoutingDecision
    tasks: tuple[PlannedTask, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": asdict(self.request),
            "analysis": self.analysis.to_dict(),
            "routing": self.routing.to_dict(),
            "tasks": [asdict(task) for task in self.tasks],
        }


class AgentsOrchestrationPipeline:
    """Dependency-light coordinator for the full public orchestration pipeline."""

    def __init__(
        self,
        registry: PersistentSkillRegistry,
        *,
        router: SkillRouter | None = None,
        analyzer: RequestAnalyzer | None = None,
        validation: ValidationEngine | None = None,
        workflow: DAGWorkflowEngine | None = None,
        rerouter: RerouteManager | None = None,
    ) -> None:
        self.registry = registry
        self.router = router or SkillRouter(registry)
        self.analyzer = analyzer or RequestAnalyzer()
        self.validation = validation or ValidationEngine()
        self.workflow = workflow or DAGWorkflowEngine()
        self.rerouter = rerouter or RerouteManager(self.router, registry)

    def prepare(
        self,
        text: str,
        *,
        explicit_skill: str | Sequence[str] | None = None,
        context_budget: int | None = None,
        available_tools: Iterable[str] | None = None,
        allowed_skill_ids: Iterable[str] | None = None,
        max_side_effect: SideEffectLevel | None = None,
        request_id: str | None = None,
        privacy_level: str = "default",
    ) -> OrchestrationPlan:
        envelope = RequestEnvelope.from_text(
            text,
            explicit_skill=explicit_skill,
            context_budget=context_budget,
            request_id=request_id,
            privacy_level=privacy_level,
        )
        return self.prepare_envelope(
            envelope,
            available_tools=available_tools,
            allowed_skill_ids=allowed_skill_ids,
            max_side_effect=max_side_effect,
        )

    def prepare_envelope(
        self,
        envelope: RequestEnvelope,
        *,
        available_tools: Iterable[str] | None = None,
        allowed_skill_ids: Iterable[str] | None = None,
        max_side_effect: SideEffectLevel | None = None,
    ) -> OrchestrationPlan:
        analysis = self.analyzer.analyze(envelope)
        routing = self.router.route(
            envelope,
            available_tools=available_tools,
            allowed_skill_ids=allowed_skill_ids,
            max_side_effect=max_side_effect,
        )
        tasks = self._tasks_from_routing(routing)
        return OrchestrationPlan(envelope, analysis, routing, tasks)

    def plan_from_routing(
        self,
        request: RequestEnvelope,
        analysis: RequestAnalysis,
        routing: RoutingDecision,
    ) -> OrchestrationPlan:
        return OrchestrationPlan(
            request,
            analysis,
            routing,
            self._tasks_from_routing(routing),
        )

    def _tasks_from_routing(
        self,
        routing: RoutingDecision,
    ) -> tuple[PlannedTask, ...]:
        if routing.status != "ROUTED":
            return ()
        incoming: dict[str, list[str]] = {
            node: [] for node in routing.dag_nodes
        }
        for dependency, node in routing.dag_edges:
            incoming.setdefault(node, []).append(dependency)
            incoming.setdefault(dependency, [])
        for skill_id in routing.selected_skills:
            incoming.setdefault(skill_id, [])
        tasks: list[PlannedTask] = []
        for skill_id in sorted(incoming):
            manifest = self.registry.get(skill_id, include_inactive=False)
            if manifest is None:
                continue
            tasks.append(
                PlannedTask(
                    task_id=f"skill:{skill_id}",
                    description=manifest.description or manifest.name,
                    skill_id=skill_id,
                    dependencies=tuple(
                        f"skill:{dependency}"
                        for dependency in sorted(incoming[skill_id])
                    ),
                    expected_output="skill_output",
                    validation=tuple(
                        manifest.validation_rules
                        or ("not_none", "no_error_field")
                    ),
                    failure_policy="classify_then_retry_fallback_or_reroute",
                    parallelizable=True,
                    side_effect=manifest.side_effect_level.value,
                )
            )
        return tuple(tasks)

    def execute(
        self,
        workflow_id: str,
        plan: OrchestrationPlan,
        runner: Callable[[PlannedTask], Any],
        *,
        max_workers: int = 4,
    ) -> WorkflowResult:
        if plan.routing.status != "ROUTED":
            raise ValueError(f"cannot execute unrouted plan: {plan.routing.status}")
        task_map = {task.task_id: task for task in plan.tasks}
        nodes = tuple(
            WorkflowNode(
                node_id=task.task_id,
                description=task.description,
                skill_id=task.skill_id,
                dependencies=task.dependencies,
                max_attempts=2,
                idempotency_key=f"{workflow_id}:{task.task_id}",
                metadata={"side_effect": task.side_effect},
            )
            for task in plan.tasks
        )
        validators: dict[str, Callable[[Any], bool]] = {
            task.task_id: self._validator(task.validation)
            for task in plan.tasks
        }

        def node_runner(node: WorkflowNode) -> Any:
            return runner(task_map[node.node_id])

        return self.workflow.execute(
            workflow_id,
            nodes,
            node_runner,
            validators=validators,
            max_workers=max_workers,
        )

    def _validator(self, names: Sequence[str]) -> Callable[[Any], bool]:
        builtins = {"not_none", "non_empty", "no_error_field"}
        selected_list: list[str] = []
        for raw_name in names:
            name = str(raw_name)
            if name in builtins:
                selected_list.append(name)
            elif name.startswith("validator:"):
                selected_list.append(name.split(":", 1)[1])
        selected = tuple(selected_list or ("not_none", "no_error_field"))

        def validate(value: Any) -> bool:
            return self.validation.run(value, selected).passed

        return validate

    def recover_route(
        self,
        plan: OrchestrationPlan,
        *,
        trigger: str,
        error: PlatformError | None = None,
        available_tools: Iterable[str] | None = None,
    ) -> RerouteResult:
        return self.rerouter.reroute(
            plan.request,
            plan.routing,
            trigger=trigger,
            error=error,
            available_tools=available_tools,
        )