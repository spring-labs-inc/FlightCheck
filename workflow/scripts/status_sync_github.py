"""GitHub Projects v2 status I/O through the owner's existing gh authentication.

Only a selected single-select value can be changed. No membership, issue,
workflow, Sequence, Priority or label mutation is implemented here.
"""

import hashlib
import json
import subprocess


class ProviderError(ValueError):
    def __init__(self, reason, detail, *, ambiguous=False):
        super().__init__(detail)
        self.reason = reason
        self.ambiguous = ambiguous


def status_identity(value):
    value = value if isinstance(value, dict) else {}
    return {k: value.get(k) for k in ("repository", "issue", "project_id", "field_id",
                                      "item_id", "option_id", "status_updated_at", "state", "state_reason")}


class GitHubProjects:
    name = "github-projects-v2"
    concurrency = "Optimistic Status value/timestamp checks and readback; GitHub supplies no atomic compare-and-set."

    def __init__(self, repository, policy, runner=None):
        self.repository = repository
        self.policy = policy
        self.runner = runner or subprocess.run

    def query(self, query, variables, *, mutation=False):
        try:
            result = self.runner(["gh", "api", "graphql", "--input", "-"],
                                 input=json.dumps({"query": query, "variables": variables}),
                                 text=True, capture_output=True, timeout=20)
            value = json.loads(result.stdout) if result.stdout else {}
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise ProviderError("provider_unavailable", "GitHub request unavailable; reconcile live state before retry.",
                                ambiguous=mutation) from error
        if (result.returncode or not isinstance(value, dict) or value.get("errors")
                or not isinstance(value.get("data"), dict)):
            raise ProviderError("provider_unavailable", "GitHub request failed; check existing access and exact configured identities.",
                                ambiguous=mutation)
        return value["data"]

    def mapping(self):
        data = self.query("""query($project:ID!,$field:ID!){
          project:node(id:$project){... on ProjectV2{id closed viewerCanUpdate}}
          field:node(id:$field){... on ProjectV2SingleSelectField{id project{id} options{id}}}}
        """, {"project": self.policy["project_id"], "field": self.policy["field_id"]})
        project, field = data.get("project"), data.get("field")
        if (not isinstance(project, dict) or project.get("id") != self.policy["project_id"]
                or not isinstance(field, dict) or field.get("id") != self.policy["field_id"]
                or not isinstance(field.get("project"), dict) or field["project"].get("id") != project["id"]):
            raise ProviderError("invalid_mapping", "Resolve the exact existing project and its single-select status field.")
        options = field.get("options")
        if (not isinstance(options, list) or any(not isinstance(v, dict) or not isinstance(v.get("id"), str) for v in options)
                or not set(self.policy["options"].values()) <= {v["id"] for v in options}):
            raise ProviderError("invalid_mapping", "Configured status option IDs do not belong to the selected field.")
        if project.get("closed") is True:
            raise ProviderError("project_unavailable", "Configured project is closed; reconcile the project policy.")
        if type(project.get("viewerCanUpdate")) is not bool:
            raise ProviderError("provider_unavailable", "Project write capability could not be observed.")
        return project

    def observe(self, issue):
        project = self.mapping()
        pieces = self.repository.split("/")
        if len(pieces) != 2 or not all(pieces):
            raise ProviderError("invalid_mapping", "GitHub repository must identify its exact owner and name.")
        cursor, found, issue_state = None, [], None
        seen = set()
        for _ in range(10):
            data = self.query("""query($owner:String!,$name:String!,$number:Int!,$cursor:String){
              repository(owner:$owner,name:$name){nameWithOwner issue(number:$number){number state stateReason
                projectItems(first:100,after:$cursor){pageInfo{hasNextPage endCursor}
                  nodes{id isArchived project{id}}}}}}
            """, {"owner": pieces[0], "name": pieces[1], "number": issue, "cursor": cursor})
            repo = data.get("repository")
            item = repo.get("issue") if isinstance(repo, dict) else None
            if (not isinstance(repo, dict) or repo.get("nameWithOwner", "").lower() != self.repository.lower()
                    or not isinstance(item, dict) or item.get("number") != issue):
                raise ProviderError("issue_unavailable", "Scoped repository issue is unavailable; verify its identity and access.")
            issue_state = {"state": item.get("state"), "state_reason": item.get("stateReason")}
            connection = item.get("projectItems")
            connection = connection if isinstance(connection, dict) else {}
            nodes, page = connection.get("nodes"), connection.get("pageInfo", {})
            if (not isinstance(nodes, list) or any(not isinstance(v, dict) or not isinstance(v.get("project"), dict) for v in nodes)
                    or not isinstance(page, dict) or type(page.get("hasNextPage")) is not bool):
                raise ProviderError("provider_unavailable", "Incomplete project-membership observation.")
            found.extend(v for v in nodes if v.get("project", {}).get("id") == project["id"])
            if not page["hasNextPage"]:
                break
            cursor = page.get("endCursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ProviderError("provider_unavailable", "Invalid membership pagination; no status was written.")
            seen.add(cursor)
        else:
            raise ProviderError("provider_unavailable", "Membership exceeds bounded observation; reconcile explicitly.")
        if not found:
            raise ProviderError("missing_membership", "Issue has no existing item in the configured project. Establish membership separately with authorization, then retry the current warranted event.")
        if len(found) != 1 or not isinstance(found[0].get("id"), str):
            raise ProviderError("ambiguous_membership", "Several matching items or an invalid item need explicit reconciliation; no item was added.")
        selected = found[0]
        if selected.get("isArchived") is not False:
            raise ProviderError("item_unavailable", "Project item is archived or its availability is unknown.")
        values, cursor, seen = [], None, set()
        for _ in range(10):
            data = self.query("""query($item:ID!,$cursor:String){node(id:$item){... on ProjectV2Item{id project{id}
              fieldValues(first:100,after:$cursor){pageInfo{hasNextPage endCursor}
                nodes{... on ProjectV2ItemFieldSingleSelectValue{optionId updatedAt
                  field{... on ProjectV2SingleSelectField{id}}}}}}}}
            """, {"item": selected["id"], "cursor": cursor})
            node = data.get("node")
            if (not isinstance(node, dict) or node.get("id") != selected["id"]
                    or not isinstance(node.get("project"), dict) or node["project"].get("id") != project["id"]):
                raise ProviderError("conflict", "Project item identity changed during observation.")
            connection = node.get("fieldValues")
            connection = connection if isinstance(connection, dict) else {}
            nodes, page = connection.get("nodes"), connection.get("pageInfo", {})
            if (not isinstance(nodes, list) or any(not isinstance(v, dict) for v in nodes)
                    or not isinstance(page, dict) or type(page.get("hasNextPage")) is not bool):
                raise ProviderError("provider_unavailable", "Incomplete status-field observation.")
            values.extend(v for v in nodes if isinstance(v.get("field"), dict)
                          and v["field"].get("id") == self.policy["field_id"])
            if not page["hasNextPage"]:
                break
            cursor = page.get("endCursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ProviderError("provider_unavailable", "Invalid field pagination; no status was written.")
            seen.add(cursor)
        else:
            raise ProviderError("provider_unavailable", "Fields exceed bounded observation; reconcile explicitly.")
        if len(values) > 1 or values and not isinstance(values[0].get("updatedAt"), str):
            raise ProviderError("provider_unavailable", "Status value is ambiguous or has no revision observation.")
        status = values[0] if values else {}
        return {"repository": self.repository, "issue": issue, "project_id": project["id"],
                "field_id": self.policy["field_id"], "item_id": selected["id"],
                "option_id": status.get("optionId"), "status_updated_at": status.get("updatedAt"),
                "writable": project["viewerCanUpdate"], **issue_state}

    def automation(self):
        rows, cursor, seen = [], None, set()
        try:
            for _ in range(10):
                data = self.query("""query($project:ID!,$cursor:String){node(id:$project){... on ProjectV2{id
                  workflows(first:100,after:$cursor){pageInfo{hasNextPage endCursor}
                    nodes{id number name enabled updatedAt}}}}}
                """, {"project": self.policy["project_id"], "cursor": cursor})
                node = data.get("node")
                if not isinstance(node, dict) or node.get("id") != self.policy["project_id"]:
                    raise ProviderError("provider_unavailable", "Project workflow identity unavailable.")
                connection = node.get("workflows")
                connection = connection if isinstance(connection, dict) else {}
                nodes, page = connection.get("nodes"), connection.get("pageInfo", {})
                if (not isinstance(nodes, list) or not isinstance(page, dict) or type(page.get("hasNextPage")) is not bool
                        or any(not isinstance(v, dict) or type(v.get("enabled")) is not bool for v in nodes)):
                    raise ProviderError("provider_unavailable", "Incomplete workflow metadata.")
                rows.extend(nodes)
                if not page["hasNextPage"]:
                    return {"available": True, "semantics_available": False, "workflows": rows,
                            "detail": "Observed actual workflow IDs/enabled metadata. This API does not expose triggers/actions; names do not establish completion semantics. Inspect those settings separately; never assume defaults."}
                cursor = page.get("endCursor")
                if not isinstance(cursor, str) or not cursor or cursor in seen:
                    raise ProviderError("provider_unavailable", "Invalid workflow pagination.")
                seen.add(cursor)
            raise ProviderError("provider_unavailable", "Workflow metadata exceeds bounded observation.")
        except ProviderError as error:
            return {"available": False, "semantics_available": False, "workflows": [], "detail": str(error)}

    def write(self, issue, option_id, expected, operation):
        # Compare the Status field itself so Priority/Sequence edits do not grant
        # authority to overwrite Status or cause unrelated-field mutations.
        current = self.observe(issue)
        if status_identity(current) != status_identity(expected):
            return {"state": "conflict", "observation": current}
        if current.get("writable") is not True:
            raise ProviderError("permission_denied", "Existing authentication cannot update this project.")
        if option_id not in self.policy["options"].values():
            raise ProviderError("invalid_mapping", "Requested option does not belong to the confirmed mapping.")
        mutation_id = hashlib.sha256(operation.encode()).hexdigest()
        self.query("""mutation($project:ID!,$item:ID!,$field:ID!,$option:String!,$client:String!){
          updateProjectV2ItemFieldValue(input:{projectId:$project,itemId:$item,fieldId:$field,
            value:{singleSelectOptionId:$option},clientMutationId:$client}){projectV2Item{id}}}
        """, {"project": self.policy["project_id"], "item": current["item_id"],
                 "field": self.policy["field_id"], "option": option_id, "client": mutation_id}, mutation=True)
        try:
            observed = self.observe(issue)
        except ProviderError as error:
            # Dispatch already happened. A read-only request's error must not
            # turn the uncertain write into a definitively unissued operation.
            raise ProviderError(error.reason, "Status mutation was dispatched but its readback is unverified; "
                                "reconcile actual state before retry. " + str(error), ambiguous=True) from error
        return {"state": "written", "observation": observed}
