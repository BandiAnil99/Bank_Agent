from app.agent import agent
from app.tools import BUSINESS_TOOLS


def test_exactly_one_agent_registers_all_four_business_tools():
    assert {tool.name for tool in BUSINESS_TOOLS} == {
        "calculate_emi",
        "check_loan_eligibility",
        "get_account_details",
        "submit_loan_application",
    }
    tool_node = agent.get_graph().nodes["tools"].data
    assert set(tool_node._tools_by_name) == {tool.name for tool in BUSINESS_TOOLS}
