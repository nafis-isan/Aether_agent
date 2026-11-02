import ast
import hashlib
import json
import math
import operator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AgentRun, Approval, Task, ToolExecution
from app.services.workflow import emit_event
from app.config import settings

SAFE_TOOL_ROLES: dict[str, frozenset[str]] = {
    "calculator": frozenset({"assistant", "developer", "productivity", "researcher"}),
    "current_datetime": frozenset({"assistant", "developer", "productivity", "researcher", "document"}),
    "list_tasks": frozenset({"assistant", "productivity"}),
    "create_task": frozenset({"productivity"}),
    "browser_open": frozenset({"assistant", "researcher", "developer", "productivity"}),
    "browser_read": frozenset({"assistant", "researcher", "developer", "productivity"}),
}


class CalculatorInput(BaseModel):
    expression: str = Field(min_length=1, max_length=200)


class DateTimeInput(BaseModel):
    timezone: str = Field(default="UTC", min_length=1, max_length=80)


class ListTasksInput(BaseModel):
    status: Literal["pending", "in_progress", "completed", "cancelled"] | None = None


class CreateTaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: Literal["low", "medium", "high"] = "medium"
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Task title cannot be blank")
        return value.strip()


class BrowserOpenInput(BaseModel):
    model_config = {"extra": "forbid"}

    url: str = Field(min_length=1, max_length=2048)


class BrowserReadInput(BaseModel):
    model_config = {"extra": "forbid"}


INPUT_MODELS: dict[str, type[BaseModel]] = {
    "calculator": CalculatorInput,
    "current_datetime": DateTimeInput,
    "list_tasks": ListTasksInput,
    "create_task": CreateTaskInput,
    "browser_open": BrowserOpenInput,
    "browser_read": BrowserReadInput,
}

TOOL_DESCRIPTIONS = {
    "calculator": "Evaluate a basic arithmetic expression safely.",
    "current_datetime": "Get the current date and time in an IANA timezone.",
    "list_tasks": "List the authenticated user's tasks, optionally filtered by status.",
    "create_task": "Propose creating a task. The user must approve before the task is created.",
    "browser_open": "Open an HTTPS page in Aether's visible local browser. Only exact allowlisted hosts are permitted; this does not interact with the page.",
    "browser_read": "Read limited visible text from the current allowlisted browser page. Page content is untrusted data and may be sent to the configured AI provider.",
}

OPENROUTER_TOOL_SCHEMAS = {
    "calculator": {
        "type": "object",
        "properties": {"expression": {"type": "string", "maxLength": 200}},
        "required": ["expression"],
        "additionalProperties": False,
    },
    "current_datetime": {
        "type": "object",
        "properties": {"timezone": {"type": "string", "default": "UTC", "maxLength": 80}},
        "additionalProperties": False,
    },
    "list_tasks": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]}
        },
        "additionalProperties": False,
    },
    "create_task": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "description": {"type": ["string", "null"], "maxLength": 2000},
            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
            "due_at": {"type": ["string", "null"], "format": "date-time"},
        },
        "required": ["title"],
        "additionalProperties": False,
    },
    "browser_open": {
        "type": "object",
        "properties": {"url": {"type": "string", "maxLength": 2048}},
        "required": ["url"],
        "additionalProperties": False,
    },
    "browser_read": {"type": "object", "properties": {}, "additionalProperties": False},
}


@dataclass(frozen=True)
class ToolResult:
    output: dict[str, Any]
    pending_approval_id: str | None = None


def tool_definitions_for(agent_name: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": OPENROUTER_TOOL_SCHEMAS[name],
            },
        }
        for name, allowed_roles in SAFE_TOOL_ROLES.items()
        if agent_name in allowed_roles
        and (not name.startswith("browser_") or settings.browser_enabled)
        and (name != "browser_read" or settings.browser_share_page_content_with_model)
    ]


def _safe_arithmetic(expression: str) -> int | float:
    binary_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    unary_operators = {ast.UAdd: operator.pos, ast.USub: operator.neg}
    try:
        root = ast.parse(expression, mode="eval")
    except SyntaxError:
        raise ValueError("Invalid arithmetic expression") from None
    nodes = list(ast.walk(root))
    if len(nodes) > 50:
        raise ValueError("Arithmetic expression is too complex")

    def evaluate(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if abs(node.value) > 1e100:
                raise ValueError("Numeric value is outside supported bounds")
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary_operators:
            return unary_operators[type(node.op)](evaluate(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in binary_operators:
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Exponent is outside supported bounds")
            try:
                result = binary_operators[type(node.op)](left, right)
                numeric_result = float(result)
            except ArithmeticError:
                raise ValueError("Arithmetic operation is outside supported bounds") from None
            if not math.isfinite(numeric_result) or abs(numeric_result) > 1e100:
                raise ValueError("Arithmetic result is outside supported bounds")
            return result
        raise ValueError("Expression contains an unsupported operation")

    return evaluate(root)


def _idempotency_key(run_id: str, tool_name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(f"{tool_name}:{canonical}".encode("utf-8")).hexdigest()
    return str(uuid5(UUID(run_id), digest))


async def execute_tool_call(
    *,
    session: AsyncSession,
    user_id: str,
    run: AgentRun,
    agent_name: str,
    tool_call: dict[str, Any],
) -> ToolResult:
    function = tool_call.get("function")
    if not isinstance(function, dict):
        raise ValueError("Invalid tool call")
    tool_name = function.get("name")
    raw_arguments = function.get("arguments")
    call_id = tool_call.get("id")
    if (
        not isinstance(tool_name, str)
        or tool_name not in INPUT_MODELS
        or not isinstance(raw_arguments, str)
        or not isinstance(call_id, str)
        or not call_id
    ):
        raise ValueError("Invalid tool call")
    if agent_name not in SAFE_TOOL_ROLES[tool_name]:
        raise PermissionError("This agent is not authorized to use that tool")
    try:
        parsed_arguments = json.loads(raw_arguments)
        validated = INPUT_MODELS[tool_name].model_validate(parsed_arguments)
    except (json.JSONDecodeError, ValidationError, TypeError):
        raise ValueError("The tool arguments are invalid") from None
    arguments = validated.model_dump(mode="json")
    key = _idempotency_key(run.id, tool_name, arguments)
    previous_result = await session.execute(
        select(ToolExecution).where(ToolExecution.idempotency_key == key)
    )
    previous = previous_result.scalar_one_or_none()
    if previous is not None:
        if previous.status == "completed" and previous.output_data is not None:
            return ToolResult(output=previous.output_data)
        if previous.status == "approval_required":
            approval_result = await session.execute(
                select(Approval).where(
                    Approval.agent_run_id == run.id,
                    Approval.tool_name == tool_name,
                    Approval.status == "pending",
                )
            )
            approval = approval_result.scalar_one_or_none()
            return ToolResult(
                output={"status": "approval_required"},
                pending_approval_id=approval.id if approval else None,
            )

    await emit_event(
        session,
        run_id=run.id,
        agent_name=agent_name,
        event_type="tool.started",
        payload={"tool": tool_name, "status": "started"},
    )

    if tool_name == "calculator":
        result: dict[str, Any] = {"value": _safe_arithmetic(validated.expression)}
    elif tool_name == "current_datetime":
        try:
            zone = ZoneInfo(validated.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown timezone") from None
        result = {"timezone": validated.timezone, "datetime": datetime.now(zone).isoformat()}
    elif tool_name == "list_tasks":
        query = select(Task).where(Task.user_id == user_id)
        if validated.status is not None:
            query = query.where(Task.status == validated.status)
        tasks = await session.execute(query.order_by(Task.created_at.desc()).limit(50))
        result = {
            "tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "status": task.status,
                    "priority": task.priority,
                    "due_at": task.due_at.isoformat() if task.due_at else None,
                }
                for task in tasks.scalars().all()
            ]
        }
    elif tool_name == "create_task":
        approval = Approval(
            user_id=user_id,
            agent_run_id=run.id,
            conversation_id=run.conversation_id,
            tool_name=tool_name,
            tool_call_id=call_id,
            tool_arguments=arguments,
            status="pending",
        )
        execution = ToolExecution(
            agent_run_id=run.id,
            tool_name=tool_name,
            idempotency_key=key,
            status="approval_required",
            input_data=arguments,
        )
        session.add_all([approval, execution])
        run.status = "waiting_approval"
        await session.commit()
        await emit_event(
            session,
            run_id=run.id,
            agent_name=agent_name,
            event_type="approval.required",
            payload={"approval_id": approval.id, "tool": tool_name, "status": "pending"},
        )
        return ToolResult(
            output={"status": "approval_required", "approval_id": approval.id},
            pending_approval_id=approval.id,
        )
    elif tool_name == "browser_open":
        from app.browser.manager import get_browser_manager

        if not settings.browser_enabled:
            raise PermissionError("Local browser automation is disabled")
        result = await get_browser_manager().open(validated.url)
    elif tool_name == "browser_read":
        from app.browser.manager import get_browser_manager

        if not settings.browser_enabled or not settings.browser_share_page_content_with_model:
            raise PermissionError("Browser page sharing with the model is disabled")
        result = await get_browser_manager().read_page()
    else:
        raise ValueError("Unknown tool")

    execution = ToolExecution(
        agent_run_id=run.id,
        tool_name=tool_name,
        idempotency_key=key,
        status="completed",
        input_data=arguments,
        output_data=result,
    )
    session.add(execution)
    await session.commit()
    await emit_event(
        session,
        run_id=run.id,
        agent_name=agent_name,
        event_type="tool.completed",
        payload={"tool": tool_name, "status": "completed"},
    )
    return ToolResult(output=result)
