"""Shared, bounded work budgets for import, generation and analysis."""

MAX_XML = 10_000_000
MAX_XML_ELEMENTS = 100_000
MAX_XML_DEPTH = 64
MAX_NODES = 2_000
MAX_EDGES = 6_000
MAX_PROMPT = 60_000
MAX_PROVIDER_BYTES = 2_000_000


def capabilities():
    return {
        "limits": {
            "xml_bytes": MAX_XML,
            "xml_elements": MAX_XML_ELEMENTS,
            "xml_depth": MAX_XML_DEPTH,
            "nodes": MAX_NODES,
            "flows": MAX_EDGES,
            "prompt_characters": MAX_PROMPT,
        },
        "supported": [
            "read_only_structural_inspection_of_unsupported_bpmn",
            "acyclic_single_process",
            "nested_single_entry_exit_embedded_subprocesses",
            "normal_multiple_end_events",
            "parallel_and_exclusive_gateways",
            "selected_trace_optimization",
            "manual_send_receive_script_business_rule_tasks_as_work",
        ],
        "unsupported": [
            "loops",
            "multi_instance",
            "event_subprocesses",
            "call_activities",
            "inclusive_event_based_complex_gateways",
            "boundary_timer_message_events",
            "multiple_process_orchestration",
            "execution_of_scripts_or_business_conditions",
        ],
    }
