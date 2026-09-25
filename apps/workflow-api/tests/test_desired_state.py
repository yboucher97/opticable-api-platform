from __future__ import annotations

import unittest

from workflow.automation.desired_state import (
    DesiredApplyResult,
    DesiredChange,
    DesiredResource,
    DesiredStateController,
    DesiredStateDocument,
    DesiredStateRegistry,
)


class FakeAdapter:
    name = "fake"

    def __init__(self, current=None):
        self.current = current
        self.applied: list[str] = []

    def plan(self, resource: DesiredResource) -> DesiredChange:
        action = "noop" if self.current == resource.desired else ("create" if self.current is None else "update")
        return DesiredChange(
            resource_id=resource.id,
            provider=resource.provider,
            kind=resource.kind,
            name=resource.name,
            action=action,
            reason="State comparison",
            current=self.current,
            desired=resource.desired,
            risk="low",
        )

    def apply(self, resource: DesiredResource, change: DesiredChange) -> DesiredApplyResult:
        self.applied.append(resource.id)
        self.current = resource.desired
        return DesiredApplyResult(
            resource_id=resource.id,
            action=change.action,
            status="completed",
            changed=change.action != "noop",
            result={"id": resource.id},
        )


class DesiredStateTests(unittest.TestCase):
    def test_plan_and_apply_is_idempotent(self) -> None:
        registry = DesiredStateRegistry()
        adapter = FakeAdapter()
        registry.register("example", "field", adapter)
        controller = DesiredStateController(registry)
        doc = DesiredStateDocument(
            name="test",
            resources=[
                DesiredResource(
                    id="example.field.customer_type",
                    provider="example",
                    kind="field",
                    name="Customer Type",
                    desired={"type": "picklist", "values": ["Commercial", "Residential"]},
                )
            ],
        )

        first = controller.plan(doc)
        self.assertEqual(first.summary, {"create": 1})
        result = controller.apply(doc, first)
        self.assertEqual(result[0].status, "completed")
        self.assertTrue(result[0].changed)

        second = controller.plan(doc)
        self.assertEqual(second.summary, {"noop": 1})

    def test_dependency_order_is_stable(self) -> None:
        registry = DesiredStateRegistry()
        adapter = FakeAdapter()
        registry.register("example", "*", adapter)
        controller = DesiredStateController(registry)
        doc = DesiredStateDocument(
            name="deps",
            resources=[
                DesiredResource(
                    id="example.workflow.lead",
                    provider="example",
                    kind="workflow",
                    name="Lead Workflow",
                    depends_on=["example.field.source"],
                    desired={},
                ),
                DesiredResource(
                    id="example.field.source",
                    provider="example",
                    kind="field",
                    name="Lead Source",
                    desired={},
                ),
            ],
        )
        plan = controller.plan(doc)
        self.assertEqual(
            [item.resource_id for item in plan.changes],
            ["example.field.source", "example.workflow.lead"],
        )

    def test_missing_adapter_becomes_manual_not_failure(self) -> None:
        controller = DesiredStateController(DesiredStateRegistry())
        doc = DesiredStateDocument(
            name="manual",
            resources=[
                DesiredResource(
                    id="forms.lead.builder",
                    provider="zoho_forms",
                    kind="builder",
                    name="Lead Form",
                    desired={"fields": []},
                )
            ],
        )
        plan = controller.plan(doc)
        self.assertEqual(plan.changes[0].action, "manual")
        self.assertTrue(plan.changes[0].requires_confirmation)

    def test_destructive_change_requires_explicit_apply_flag(self) -> None:
        class DeleteAdapter(FakeAdapter):
            def plan(self, resource: DesiredResource) -> DesiredChange:
                return DesiredChange(
                    resource_id=resource.id,
                    provider=resource.provider,
                    kind=resource.kind,
                    name=resource.name,
                    action="delete",
                    reason="Retire managed resource",
                    current={"exists": True},
                    desired=None,
                    risk="destructive",
                    requires_confirmation=True,
                )

        registry = DesiredStateRegistry()
        registry.register("example", "resource", DeleteAdapter({"exists": True}))
        controller = DesiredStateController(registry)
        doc = DesiredStateDocument(
            name="delete",
            resources=[
                DesiredResource(
                    id="example.resource.old",
                    provider="example",
                    kind="resource",
                    name="Old Resource",
                    desired={},
                )
            ],
        )
        plan = controller.plan(doc)
        blocked = controller.apply(doc, plan, allow_destructive=False)
        self.assertEqual(blocked[0].status, "blocked")
        self.assertFalse(blocked[0].changed)

    def test_cycle_is_rejected(self) -> None:
        registry = DesiredStateRegistry()
        registry.register("example", "*", FakeAdapter())
        controller = DesiredStateController(registry)
        doc = DesiredStateDocument(
            name="cycle",
            resources=[
                DesiredResource(id="a", provider="example", kind="x", name="A", desired={}, depends_on=["b"]),
                DesiredResource(id="b", provider="example", kind="x", name="B", desired={}, depends_on=["a"]),
            ],
        )
        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            controller.plan(doc)


if __name__ == "__main__":
    unittest.main()
