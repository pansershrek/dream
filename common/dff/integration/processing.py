import logging

from dff.core import Context, Actor

import common.constants as common_constants
from . import context


logger = logging.getLogger(__name__)


def save_slots_to_ctx(slots: dict):
    def save_slots_to_ctx_processing(
        ctx: Context,
        actor: Actor,
        *args,
        **kwargs,
    ) -> Context:
        ctx.misc["slots"] = ctx.misc.get("slots", {}) | slots
        return ctx

    return save_slots_to_ctx_processing


def fill_responses_by_slots():
    def fill_responses_by_slots_processing(
        ctx: Context,
        actor: Actor,
        *args,
        **kwargs,
    ) -> Context:
        processed_node = ctx.a_s.get("processed_node", ctx.a_s["next_node"])
        for slot_name, slot_value in ctx.misc.get("slots", {}).items():
            processed_node.response = processed_node.response.replace("{" f"{slot_name}" "}", slot_value)
        ctx.a_s["processed_node"] = processed_node
        return ctx

    return fill_responses_by_slots_processing


def set_confidence(confidence: float = 1.0):
    def set_confidence_processing(
        ctx: Context,
        actor: Actor,
        *args,
        **kwargs,
    ) -> Context:
        context.set_confidence(ctx, actor, confidence)
        return ctx

    return set_confidence_processing


def set_can_continue(continue_flag: str = common_constants.CAN_CONTINUE_SCENARIO):
    def set_can_continue_processing(
        ctx: Context,
        actor: Actor,
        *args,
        **kwargs,
    ) -> Context:
        context.set_can_continue(ctx, actor, continue_flag)
        return ctx

    return set_can_continue_processing
