from copy import deepcopy
import json
import unittest

from ascendra.capability_agent import CapabilityAgent, ACTION_SCHEMA, GOAL_SCHEMA, execute_workflow


class Catalogue:
    def __init__(self):
        self.calls=[]

    def descriptors(self):
        return [{"name":name,"description":name,"input_schema":{"type":"object"}}
                for name in ("read_file","search_text","run_tests")]

    def execute(self,name,args):
        self.calls.append((name,deepcopy(args)))
        if name=="read_file" and args.get("path")=="missing.py":
            return {"status":"error","tool":name,"error":"File does not exist"}
        if name not in {d["name"] for d in self.descriptors()}:
            return {"status":"error","error":"Unknown tool"}
        return {"status":"ok","tool":name,"data":{"successful":False,"tests_run":1}}


class Store:
    def __init__(self):
        self.episodes=[];self.capabilities=[]

    def context(self):
        return {"episodes":deepcopy(self.episodes)}

    def record_episode(self,episode):
        self.episodes.append(deepcopy(episode));return "episode_"+str(len(self.episodes))

    def list_capabilities(self,status=None):
        return deepcopy([c for c in self.capabilities if status is None or c["status"]==status])

    def propose(self,spec):
        if spec.get("verified"):
            raise ValueError("Cannot self-verify")
        identifier="proposal_"+str(len(self.capabilities)+1)
        self.capabilities.append({"id":identifier,"spec":deepcopy(spec),"status":"proposed"})
        return identifier


def proposal():
    return {"name":"Inspect then test","description":"Inspect a Python file and run its tests",
            "motivation":"Recover evidence before changing code","success_criteria":"Read the source and report test outcome",
            "input_schema":{"type":"object","properties":{"file":{"type":"string"}},
                            "required":["file"],"additionalProperties":False},
            "steps":[{"tool":"read_file","arguments":{"path":"$input.file"}},
                     {"tool":"run_tests","arguments":{}}]}


class CapabilityAgentTests(unittest.TestCase):
    def test_model_changes_tool_from_actual_feedback_and_next_episode_memory(self):
        catalog,store=Catalogue(),Store()
        requests=[]
        def decide(request,schema):
            requests.append(deepcopy(request))
            if not request["recent_results"]:
                return {"action":"tool","tool":"read_file","arguments":{"path":"missing.py"}}
            if request["recent_results"][-1].get("result",{}).get("status")=="error":
                return {"action":"tool","tool":"search_text","arguments":{"query":"actual module"}}
            return {"action":"finish","message":"Located evidence"}
        result=CapabilityAgent(catalog,store,decide).run("Inspect the project")
        self.assertEqual([x[0] for x in catalog.calls],["read_file","search_text"])
        self.assertIsNone(result["objective_success"])
        self.assertEqual(result["episode_id"],"episode_1")
        def next_decision(request,schema):
            history=request["learned_context"]["episodes"]
            self.assertEqual(history[0]["tool_observations"][0]["error"],"File does not exist")
            return {"action":"finish","message":"Use known file location next"}
        CapabilityAgent(catalog,store,next_decision).run("Continue learning")
        self.assertEqual(len(store.episodes),2)

    def test_proposal_stays_unverified_and_unavailable(self):
        catalog,store=Catalogue(),Store();calls=0
        def decide(request,schema):
            nonlocal calls
            calls+=1
            if calls==1:
                return {"action":"propose","proposal":proposal()}
            self.assertFalse(any(d["name"].startswith("capability:") for d in request["tool_catalog"]))
            return {"action":"tool","tool":"capability:proposal_1","arguments":{"file":"main.py"}}
        result=CapabilityAgent(catalog,store,decide,max_steps=2).run("Invent a diagnostic workflow")
        self.assertEqual(store.capabilities[0]["status"],"proposed")
        self.assertEqual(result["proposal_ids"],["proposal_1"])
        self.assertFalse(result["tool_observations"][0]["execution_success"])
        self.assertEqual(catalog.calls,[])

    def test_verified_workflow_reuse_substitutes_inputs_without_certifying_goal(self):
        catalog,store=Catalogue(),Store()
        store.capabilities=[{"id":"verified_1","status":"verified","spec":proposal()}]
        def decide(request,schema):
            self.assertIn("capability:verified_1",[d["name"] for d in request["tool_catalog"]])
            return {"action":"tool","tool":"capability:verified_1","arguments":{"file":"src/main.py"}}
        result=CapabilityAgent(catalog,store,decide,max_steps=2,max_proposals=0).run("Use trusted diagnostic")
        self.assertEqual(catalog.calls[0],("read_file",{"path":"src/main.py"}))
        self.assertTrue(result["tool_observations"][0]["execution_success"])
        self.assertIsNone(result["objective_success"])
        self.assertFalse(result["steps"][0]["result"]["steps"][1]["result"]["data"]["successful"])

    def test_workflow_prevalidates_all_steps_and_disallows_recursion(self):
        catalog=Catalogue();spec=proposal()
        spec["steps"].append({"tool":"capability:any","arguments":{}})
        result=execute_workflow(spec,{"file":"main.py"},catalog)
        self.assertEqual(result["status"],"error")
        self.assertEqual(catalog.calls,[])
        self.assertEqual(execute_workflow(proposal(),{},catalog)["status"],"error")
        self.assertEqual(execute_workflow(proposal(),{"file":7},catalog)["status"],"error")

    def test_workflow_no_eval_and_rejects_missing_or_malformed_placeholders(self):
        catalog=Catalogue();spec=proposal()
        for placeholder in ("$input.file.__class__","$input.file()","$input.missing"):
            spec["steps"][0]["arguments"]["path"]=placeholder
            self.assertEqual(execute_workflow(spec,{"file":"main.py"},catalog)["status"],"error")
        self.assertEqual(catalog.calls,[])

    def test_step_and_proposal_limits_stop_boundedly(self):
        catalog,store=Catalogue(),Store()
        agent=CapabilityAgent(catalog,store,lambda r,s:{"action":"tool","tool":"unknown","arguments":{}},max_steps=3)
        result=agent.run("Find suitable tools")
        self.assertEqual(len(result["steps"]),3)
        self.assertEqual(result["stop_reason"],"step_limit")
        other=CapabilityAgent(catalog,store,lambda r,s:{"action":"propose","proposal":proposal()},max_steps=5,max_proposals=1)
        result=other.run("Propose a bounded workflow")
        self.assertEqual(result["stop_reason"],"proposal_limit")
        self.assertEqual(len(result["proposal_ids"]),1)

    def test_strict_wire_json_and_invalid_model_output(self):
        catalog,store=Catalogue(),Store()
        self.assertFalse(ACTION_SCHEMA["additionalProperties"])
        self.assertEqual(set(ACTION_SCHEMA["properties"]),set(ACTION_SCHEMA["required"]))
        decision={"action":"tool","tool":"read_file","arguments_json":json.dumps({"path":"main.py"}),"proposal_json":None,"message":None}
        result=CapabilityAgent(catalog,store,lambda r,s:decision,max_steps=1,max_proposals=0).run("Inspect")
        self.assertEqual(catalog.calls,[("read_file",{"path":"main.py"})])
        self.assertEqual(result["stop_reason"],"step_limit")
        decision["arguments_json"]="not json"
        result=CapabilityAgent(catalog,store,lambda r,s:decision).run("Inspect")
        self.assertEqual(result["stop_reason"],"decision_error")

    def test_choose_own_goal_uses_experience_without_new_permissions(self):
        catalog,store=Catalogue(),Store()
        store.record_episode({"objective":"Previous failure","tool_observations":[],"objective_success":None})
        def decide(request,schema):
            self.assertEqual(schema,GOAL_SCHEMA)
            self.assertEqual(len(request["learned_context"]["episodes"]),1)
            return {"goal":"Learn to locate the correct test directory","rationale":"Previous attempt lacked project layout evidence","target_capability":"project discovery"}
        result=CapabilityAgent(catalog,store,decide).choose_goal()
        self.assertIn("test directory",result["goal"])
        self.assertEqual(catalog.calls,[])
        self.assertEqual(store.capabilities,[])


if __name__=="__main__":
    unittest.main()
