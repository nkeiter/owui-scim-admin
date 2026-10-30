#!/usr/bin/env python3
"""Open WebUI SCIM Admin

Developed by Nathan I Keiter, Gettysburg College.

Administer OpenWebUI SCIM 2.0 users and groups.

Examples:
	# Users
	python3 %(prog)s list-users --filter 'userName eq "user@example.com"'
	python3 %(prog)s list-users --filter-name "smith"
	python3 %(prog)s list-users --filter-username "smith"
	python3 %(prog)s list-users --format csv --export users.csv
	python3 %(prog)s get-user --id USER_ID
	python3 %(prog)s create-user --user-name user@example.com \
	  --given-name Ada --family-name Lovelace --external-id idp-123
	python3 %(prog)s update-user --id USER_ID --method put \
	  --user-name ada@example.com --primary-email ada@example.com --active
	python3 %(prog)s update-user --id USER_ID --method patch \
	  --operation '{"op":"replace","path":"active","value":false}'
	python3 %(prog)s delete-user --id USER_ID

	# Groups
	python3 %(prog)s list-groups --filter 'displayName eq "Engineering"'
	python3 %(prog)s list-groups --filter-name "engineering"
	python3 %(prog)s list-groups --show-members --export-only groups.txt
	python3 %(prog)s get-group --id GROUP_ID
	python3 %(prog)s create-group --display-name Engineering --member USER_ID
	python3 %(prog)s update-group --id GROUP_ID --method put \
	  --display-name Engineering --member USER_ID
	python3 %(prog)s update-group --id GROUP_ID --method patch \
	  --operation '{"op":"add","path":"members","value":[{"value":"USER_ID"}]}'
	python3 %(prog)s delete-group --id GROUP_ID

	# CSV import
	# CSV has no headers: action,group,userName[,ignored...]
	# action is "add" or "drop". Imports both users and groups from the CSV.
	# Missing users/groups are created; memberships are added or removed per row.
	python3 %(prog)s --app-env dev import-groups roster.csv

SCIM_TOKEN is read from the environment unless --scim-token is supplied. APP_ENV
is read from the environment unless --app-env is supplied. The command-line
values take precedence. APP_ENV must be dev or prod, with the corresponding
SCIM_DEV_URL or SCIM_PROD_URL set. SCIM_EMAIL_DOMAIN is required only when
using a username without an @ address.
"""

import argparse
import csv
import io
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ENV_URL_VARIABLES = {
	"dev": "SCIM_DEV_URL",
	"prod": "SCIM_PROD_URL",
}
HELP_EXAMPLES = """Examples:
	python3 %(prog)s list-users --filter 'userName eq "user@example.com"'
	python3 %(prog)s list-users --filter-name "smith"
	python3 %(prog)s list-users --filter-username "smith"
	python3 %(prog)s list-users --format csv --export users.csv
	python3 %(prog)s get-user --id USER_ID
	python3 %(prog)s create-user --user-name user@example.com --given-name Ada --family-name Lovelace
	python3 %(prog)s update-user --id USER_ID --method put --user-name user@example.com --active
	python3 %(prog)s update-user --id USER_ID --method patch --operation '{"op":"replace","path":"active","value":false}'
	python3 %(prog)s delete-user --id USER_ID
	python3 %(prog)s list-groups --filter 'displayName eq "Engineering"'
	python3 %(prog)s list-groups --filter-name "engineering"
	python3 %(prog)s list-groups --show-members --export-only groups.txt
	python3 %(prog)s get-group --id GROUP_ID
	python3 %(prog)s create-group --display-name Engineering --member USER_ID
	python3 %(prog)s update-group --id GROUP_ID --method put --display-name Engineering --member USER_ID
	python3 %(prog)s update-group --id GROUP_ID --method patch --operation '{"op":"add","path":"members","value":[{"value":"USER_ID"}]}'
	python3 %(prog)s delete-group --id GROUP_ID
	python3 %(prog)s import-groups roster.csv
	python3 %(prog)s requirements --mode both"""


STATS = {"users_created": 0, "users_updated": 0, "groups_created": 0, "groups_updated": 0}


def record_created(resource):
	STATS["users_created" if resource == "Users" else "groups_created"] += 1


def record_updated(resource):
	STATS["users_updated" if resource == "Users" else "groups_updated"] += 1


def print_summary():
	if not any(STATS.values()):
		return
	print(
		f"Summary: {STATS['groups_updated']} group(s) updated, {STATS['groups_created']} group(s) created, "
		f"{STATS['users_updated']} user(s) updated, {STATS['users_created']} user(s) created."
	)


def fail(message):
	print(f"ERROR: {message}", file=sys.stderr)
	raise SystemExit(2)


def resolve_configuration(args):
	token = args.scim_token or os.environ.get("SCIM_TOKEN")
	app_env = (args.app_env or os.environ.get("APP_ENV") or "").strip().lower()
	if not token:
		fail("SCIM_TOKEN is not set. Export it or pass --scim-token.")
	if app_env not in ENV_URL_VARIABLES:
		fail("APP_ENV must be 'dev' or 'prod'. Export it or pass --app-env.")
	url_variable = ENV_URL_VARIABLES[app_env]
	url_argument = "scim_dev_url" if app_env == "dev" else "scim_prod_url"
	base_url = (getattr(args, url_argument, None) or os.environ.get(url_variable) or "").strip()
	if not base_url:
		fail(
			f"{url_variable} is not set. Export it or pass "
			f"--{url_argument.replace('_', '-')} for the selected environment."
		)
	return token, base_url.rstrip("/")


def request_scim(args, method, path, payload=None, query=None):
	token, base_url = resolve_configuration(args)
	url = f"{base_url}/{path.lstrip('/')}"
	if query:
		url = f"{url}?{urlencode({key: value for key, value in query.items() if value is not None})}"

	data = json.dumps(payload).encode("utf-8") if payload is not None else None
	headers = {
		"Authorization": f"Bearer {token}",
		"Accept": "application/scim+json, application/json",
	}
	if data is not None:
		headers["Content-Type"] = "application/scim+json"

	try:
		with urlopen(Request(url, data=data, headers=headers, method=method), timeout=args.timeout) as response:
			body = response.read().decode("utf-8")
			if not body:
				return response.status, None
			try:
				return response.status, json.loads(body)
			except json.JSONDecodeError:
				content_type = response.headers.get("Content-Type", "unknown")
				preview = body.strip().replace("\n", " ")[:500]
				fail(
					f"SCIM API returned HTTP {response.status} with non-JSON content "
					f"(Content-Type: {content_type}). Response preview: {preview!r}. "
					"Verify the SCIM endpoint and any proxy or authentication gateway."
				)
	except HTTPError as exc:
		body = exc.read().decode("utf-8", errors="replace")
		try:
			detail = json.dumps(json.loads(body), indent=2, sort_keys=True)
		except json.JSONDecodeError:
			detail = body or exc.reason
		fail(f"SCIM API returned HTTP {exc.code}: {detail}")
	except URLError as exc:
		fail(f"Could not reach the SCIM API: {exc.reason}")


def print_response(status, body):
	if body is None:
		print(f"HTTP {status}")
	else:
		print(json.dumps(body, indent=2, sort_keys=True))


def parse_json(value, option_name):
	try:
		return json.loads(value)
	except json.JSONDecodeError as exc:
		fail(f"{option_name} must contain valid JSON: {exc.msg}")


def add_if_set(payload, key, value):
	if value is not None:
		payload[key] = value


def derive_user_identity(user_name, configured_email_domain=None):
	if "@" in user_name and user_name.rsplit("@", 1)[1].strip():
		return user_name.split("@", 1)[0], user_name
	if "@" in user_name:
		user_name = user_name.rsplit("@", 1)[0].strip()
	email_domain = (
		configured_email_domain or os.environ.get("SCIM_EMAIL_DOMAIN", "")
	).strip().lstrip("@")
	if not email_domain:
		fail(
			"SCIM_EMAIL_DOMAIN is required when a username without an email address is used. "
			"Provide a complete email address or configure SCIM_EMAIL_DOMAIN."
		)
	return user_name, f"{user_name}@{email_domain}"


def build_user(args, include_schema=True):
	if args.json:
		payload = parse_json(args.json, "--json")
		if not isinstance(payload, dict):
			fail("--json must be a JSON object")
		return payload

	payload = {"schemas": [SCIM_USER_SCHEMA]} if include_schema else {}
	derived_email = None
	if args.user_name:
		username, derived_email = derive_user_identity(
			args.user_name, getattr(args, "scim_email_domain", None)
		)
		payload["userName"] = username
	add_if_set(payload, "displayName", args.display_name)
	add_if_set(payload, "externalId", args.external_id)
	if args.active is not None:
		payload["active"] = args.active
	name = {}
	add_if_set(name, "givenName", args.given_name)
	add_if_set(name, "familyName", args.family_name)
	if name:
		payload["name"] = name
	if args.email:
		payload["emails"] = [
			{"value": email, "primary": email == args.primary_email}
			for email in args.email
		]
	elif args.primary_email:
		payload["emails"] = [{"value": args.primary_email, "primary": True}]
	elif derived_email:
		payload["emails"] = [{"value": derived_email, "primary": True}]
	return payload


def build_group(args, include_schema=True):
	if args.json:
		payload = parse_json(args.json, "--json")
		if not isinstance(payload, dict):
			fail("--json must be a JSON object")
		return payload

	payload = {"schemas": [SCIM_GROUP_SCHEMA]} if include_schema else {}
	add_if_set(payload, "displayName", args.display_name)
	add_if_set(payload, "externalId", args.external_id)
	if args.member:
		payload["members"] = [{"value": member} for member in args.member]
	return payload


def resource_name(resource):
	name = resource.get("name") or {}
	family_name = name.get("familyName")
	given_name = name.get("givenName")
	if family_name and given_name:
		return f"{family_name}, {given_name}"
	if family_name or given_name:
		return family_name or given_name
	return resource.get("displayName") or resource.get("userName") or resource.get("id", "(unnamed user)")


def user_sort_key(user):
	name = user.get("name") or {}
	return (
		(name.get("familyName") or "").casefold(),
		(name.get("givenName") or "").casefold(),
		resource_name(user).casefold(),
	)


def resources_from_response(body):
	if not isinstance(body, dict):
		fail("SCIM list response is not a JSON object")
	resources = body.get("Resources", [])
	if not isinstance(resources, list):
		fail("SCIM list response has no valid Resources array")
	return resources


def fetch_list_resources(args, resource, query):
	start_index = query.get("startIndex") or 1
	maximum_results = query.get("count")
	page_size = min(maximum_results, 100) if maximum_results else 100
	resources = []

	while True:
		page_query = dict(query, startIndex=start_index, count=page_size)
		_, body = request_scim(args, "GET", resource, query=page_query)
		page_resources = resources_from_response(body)
		remaining_results = maximum_results - len(resources) if maximum_results else None
		resources.extend(page_resources[:remaining_results])

		if maximum_results and len(resources) >= maximum_results:
			break
		if not page_resources:
			break

		items_per_page = body.get("itemsPerPage")
		if not isinstance(items_per_page, int) or items_per_page < 1:
			items_per_page = len(page_resources)
		start_index += items_per_page

		total_results = body.get("totalResults")
		if isinstance(total_results, int) and start_index > total_results:
			break
		if not isinstance(total_results, int) and len(page_resources) < page_size:
			break

	return resources


def filter_resources(resource, resources, filter_name, filter_username):
	if not filter_name and not filter_username:
		return resources

	needle = (filter_name or filter_username).casefold()
	if resource == "Users":
		if filter_username:
			return [user for user in resources if needle in (user.get("userName") or "").casefold()]
		return [
			user for user in resources
			if needle in (user.get("name") or {}).get("familyName", "").casefold()
			or needle in (user.get("name") or {}).get("givenName", "").casefold()
		]

	return [group for group in resources if needle in (group.get("displayName") or "").casefold()]


def apply_simple_filters(args, resources):
	resources = filter_resources(args.resource, resources, args.filter_name, args.filter_username)
	return resources[:args.count] if args.count else resources


def render_csv(resource, resources):
	output = io.StringIO()
	if resource == "Users":
		writer = csv.DictWriter(output, fieldnames=("id", "userName", "givenName", "familyName", "active"))
		writer.writeheader()
		for user in sorted(resources, key=user_sort_key):
			name = user.get("name") or {}
			writer.writerow({
				"id": user.get("id", ""),
				"userName": user.get("userName", ""),
				"givenName": name.get("givenName", ""),
				"familyName": name.get("familyName", ""),
				"active": user.get("active", ""),
			})
	else:
		writer = csv.DictWriter(output, fieldnames=("id", "displayName", "memberCount"))
		writer.writeheader()
		for group in sorted(resources, key=lambda item: item.get("displayName", "").casefold()):
			writer.writerow({
				"id": group.get("id", ""),
				"displayName": group.get("displayName", ""),
				"memberCount": len(group.get("members") or []),
			})
	return output.getvalue()


def render_names(resource, resources, users_by_id, show_members):
	if resource == "Users":
		return "\n".join(resource_name(user) for user in sorted(resources, key=user_sort_key)) + ("\n" if resources else "")

	lines = []
	for group in sorted(resources, key=lambda item: item.get("displayName", "").casefold()):
		members = group.get("members") or []
		lines.append(f"{group.get('displayName') or '(unnamed group)'} - ({len(members)} members)")
		if show_members:
			member_users = []
			for member in members:
				user = users_by_id.get(member.get("value"))
				if user:
					member_users.append(user)
				else:
					member_users.append({"displayName": member.get("display") or member.get("value", "(unknown member)")})
			for user in sorted(member_users, key=user_sort_key):
				lines.append(f"    {resource_name(user)}")
	return "\n".join(lines) + ("\n" if lines else "")


def write_list_output(args, output):
	if args.export or args.export_only:
		filename = args.export or args.export_only
		try:
			with open(filename, "w", encoding="utf-8", newline="") as export_file:
				export_file.write(output)
		except OSError as exc:
			fail(f"Could not export output to {filename!r}: {exc}")
	if not args.export_only:
		print(output, end="")


def read_group_import(filename, email_domain=None):
	try:
		with open(filename, encoding="utf-8-sig", newline="") as import_file:
			reader = csv.reader(import_file)
			groups = {}
			skipped_missing_domain = []
			for line_number, row in enumerate(reader, start=1):
				if not row or not any(cell.strip() for cell in row):
					continue
				if len(row) < 3:
					fail(f"Import CSV line {line_number} must provide action, group, and userName")
				action = row[0].strip().lower()
				group_name = row[1].strip()
				raw_username = row[2].strip()
				if action not in ("add", "drop"):
					fail(f"Import CSV line {line_number} action must be 'add' or 'drop', got {row[0]!r}")
				if not group_name or not raw_username:
					fail(f"Import CSV line {line_number} must provide both group and userName")
				has_email_domain = "@" in raw_username and bool(raw_username.rsplit("@", 1)[1].strip())
				configured_domain = (
					email_domain or os.environ.get("SCIM_EMAIL_DOMAIN", "")
				).strip().lstrip("@")
				if not has_email_domain and not configured_domain:
					skipped_missing_domain.append((line_number, raw_username))
					continue
				username, email = derive_user_identity(raw_username, configured_domain)
				group_key = group_name.casefold()
				if group_key not in groups:
					groups[group_key] = {"display_name": group_name, "adds": {}, "drops": {}}
				if action == "add":
					groups[group_key]["adds"].setdefault(username.casefold(), (username, email))
				else:
					groups[group_key]["drops"].setdefault(username.casefold(), (username, email))
	except OSError as exc:
		fail(f"Could not read import CSV {filename!r}: {exc}")
	return groups, skipped_missing_domain


def report_missing_email_domains(skipped_rows):
	if not skipped_rows:
		return
	details = "; ".join(
		f"line {line_number} ({username!r})" for line_number, username in skipped_rows
	)
	fail(
		"CSV import skipped row(s) because the userName has no email domain and "
		"no default email domain was configured. Provide an email domain in the "
		"CSV value or set SCIM_EMAIL_DOMAIN/--scim-email-domain. Skipped: "
		f"{details}"
	)



def load_all_users(args):
	# The SCIM API stores userName as the email address, so index by both to catch either form.
	resources = fetch_list_resources(args, "Users", {})
	cache = {}
	for user in resources:
		user_name = (user.get("userName") or "").casefold()
		if user_name:
			cache[user_name] = user
		for email in user.get("emails") or []:
			value = (email.get("value") or "").casefold()
			if value:
				cache[value] = user
	return cache


def load_all_groups(args):
	resources = fetch_list_resources(args, "Groups", {})
	return {(group.get("displayName") or "").casefold(): group for group in resources if group.get("displayName")}


def find_existing_user(username, email, cache):
	return cache.get(username.casefold()) or cache.get(email.casefold())


def find_existing_group(group_name, cache):
	return cache.get(group_name.casefold())


def create_import_user(args, username, email):
	payload = {
		"schemas": [SCIM_USER_SCHEMA],
		"userName": username,
		"displayName": username,
		"emails": [{"value": email, "primary": True}],
		"active": True,
	}
	_, user = request_scim(args, "POST", "Users", payload)
	if not isinstance(user, dict) or not user.get("id"):
		fail(f"SCIM API did not return an ID while creating user {username!r}")
	record_created("Users")
	return user


def create_import_group(args, group_name):
	payload = {"schemas": [SCIM_GROUP_SCHEMA], "displayName": group_name}
	_, group = request_scim(args, "POST", "Groups", payload)
	if not isinstance(group, dict) or not group.get("id"):
		fail(f"SCIM API did not return an ID while creating group {group_name!r}")
	record_created("Groups")
	return group


def extract_missing_fields(parsed):
	fields = []
	detail = parsed.get("detail") if isinstance(parsed, dict) else None
	if isinstance(detail, list):
		for item in detail:
			if not isinstance(item, dict):
				continue
			item_type = (item.get("type") or "").lower()
			msg = (item.get("msg") or "").lower()
			if item_type == "missing" or "required" in msg:
				loc = item.get("loc") or []
				if loc:
					fields.append(str(loc[-1]))
	seen = set()
	unique_fields = []
	for field in fields:
		if field not in seen:
			seen.add(field)
			unique_fields.append(field)
	return unique_fields


def probe_required_fields(args, resource):
	# Send an empty create payload and read back which fields the API reports as missing.
	token, base_url = resolve_configuration(args)
	url = f"{base_url}/{resource}"
	headers = {
		"Authorization": f"Bearer {token}",
		"Accept": "application/scim+json, application/json",
		"Content-Type": "application/scim+json",
	}
	data = json.dumps({}).encode("utf-8")
	try:
		with urlopen(Request(url, data=data, headers=headers, method="POST"), timeout=args.timeout) as response:
			body = response.read().decode("utf-8")
			created = json.loads(body) if body else {}
	except HTTPError as exc:
		error_body = exc.read().decode("utf-8", errors="replace")
		try:
			parsed = json.loads(error_body)
		except json.JSONDecodeError:
			fail(f"Could not parse SCIM error response for {resource}: {error_body[:300]!r}")
		fields = extract_missing_fields(parsed)
		if not fields:
			fail(
				f"SCIM API returned HTTP {exc.code} while probing {resource} but no missing-field details "
				f"were found in the response: {json.dumps(parsed)[:300]}"
			)
		return fields
	except URLError as exc:
		fail(f"Could not reach the SCIM API: {exc.reason}")

	# The API unexpectedly accepted an empty payload; clean up any resource it created.
	resource_id = created.get("id") if isinstance(created, dict) else None
	if resource_id:
		try:
			cleanup_headers = {"Authorization": f"Bearer {token}", "Accept": "application/scim+json, application/json"}
			urlopen(Request(f"{url}/{resource_id}", headers=cleanup_headers, method="DELETE"), timeout=args.timeout).close()
		except (HTTPError, URLError):
			pass
	return []


def show_requirements(args):
	sections = []
	if args.mode in ("both", "groups"):
		sections.append(("Groups", probe_required_fields(args, "Groups")))
	if args.mode in ("both", "users"):
		sections.append(("Users", probe_required_fields(args, "Users")))
	for name, fields in sections:
		print(f"Required fields for {name}:")
		if fields:
			for field in fields:
				print(f"    {field}")
		else:
			print("    (none detected; the API accepted an empty payload)")


def add_group_members(args, group, user_ids):
	existing_member_ids = {member.get("value") for member in group.get("members") or []}
	new_member_ids = sorted(user_ids - existing_member_ids)
	if not new_member_ids:
		return 0
	payload = {
		"schemas": [SCIM_PATCH_SCHEMA],
		"Operations": [{"op": "add", "path": "members", "value": [{"value": user_id} for user_id in new_member_ids]}],
	}
	request_scim(args, "PATCH", f"Groups/{group['id']}", payload)
	record_updated("Groups")
	group["members"] = (group.get("members") or []) + [{"value": user_id} for user_id in new_member_ids]
	return len(new_member_ids)


def remove_group_members(args, group, user_ids):
	existing_member_ids = {member.get("value") for member in group.get("members") or []}
	remove_member_ids = sorted(user_ids & existing_member_ids)
	if not remove_member_ids:
		return 0
	payload = {
		"schemas": [SCIM_PATCH_SCHEMA],
		"Operations": [{"op": "remove", "path": "members", "value": [{"value": user_id} for user_id in remove_member_ids]}],
	}
	request_scim(args, "PATCH", f"Groups/{group['id']}", payload)
	record_updated("Groups")
	group["members"] = [member for member in (group.get("members") or []) if member.get("value") not in set(remove_member_ids)]
	return len(remove_member_ids)


def import_groups(args):
	requested_groups, skipped_missing_domain = read_group_import(
		args.filename, args.scim_email_domain
	)
	if skipped_missing_domain and not requested_groups:
		report_missing_email_domains(skipped_missing_domain)
	user_cache = load_all_users(args)
	group_cache = load_all_groups(args)
	members_added = 0
	members_removed = 0

	for group_key in sorted(requested_groups):
		group_info = requested_groups[group_key]
		group_name = group_info["display_name"]
		needs_group = group_info["adds"] or group_info["drops"]
		if not needs_group:
			continue
		group = find_existing_group(group_name, group_cache)
		if not group:
			group = create_import_group(args, group_name)
			group_cache[group_key] = group

		add_ids = set()
		for username, email in sorted(group_info["adds"].values(), key=lambda pair: pair[0].casefold()):
			user = find_existing_user(username, user_cache)
			if not user:
				user = create_import_user(args, username, email)
				user_cache[username.casefold()] = user
			add_ids.add(user["id"])
		members_added += add_group_members(args, group, add_ids)

		drop_ids = set()
		for username, _ in sorted(group_info["drops"].values(), key=lambda pair: pair[0].casefold()):
			user = find_existing_user(username, user_cache)
			if user:
				drop_ids.add(user["id"])
		members_removed += remove_group_members(args, group, drop_ids)

	print(
		f"Processed {len(requested_groups)} group(s) from {args.filename!r}: "
		f"added {members_added} membership(s), removed {members_removed} membership(s)."
	)
	report_missing_email_domains(skipped_missing_domain)


def list_resources(args):
	if args.show_members and args.resource != "Groups":
		fail("--show-members is available only with list-groups")
	if args.show_members and args.format != "names":
		fail("--show-members requires --format names")
	if args.filter_username and args.resource != "Users":
		fail("--filter-username is available only with list-users")
	query = {
		"filter": args.filter,
		"startIndex": args.start_index,
		"count": args.count,
		"attributes": args.attributes,
	}
	client_filtering = bool(args.filter_name or args.filter_username)
	if client_filtering:
		query["count"] = None
	if args.format == "json":
		if not client_filtering:
			_, body = request_scim(args, "GET", args.resource, query=query)
		else:
			resources = fetch_list_resources(args, args.resource, query)
			resources = apply_simple_filters(args, resources)
			body = {"Resources": resources, "totalResults": len(resources)}
		output = json.dumps(body, indent=2, sort_keys=True) + "\n"
		write_list_output(args, output)
		return

	resources = fetch_list_resources(args, args.resource, query)
	resources = apply_simple_filters(args, resources)
	if args.format == "csv":
		write_list_output(args, render_csv(args.resource, resources))
		return

	users_by_id = {}
	if args.resource == "Groups" and args.show_members:
		users_by_id = {user.get("id"): user for user in fetch_list_resources(args, "Users", {}) if user.get("id")}
	write_list_output(args, render_names(args.resource, resources, users_by_id, args.show_members))


def get_resource(args):
	status, body = request_scim(args, "GET", f"{args.resource}/{args.id}", query={"attributes": args.attributes})
	print_response(status, body)


def create_resource(args):
	payload = build_user(args) if args.resource == "Users" else build_group(args)
	required_attribute = "userName" if args.resource == "Users" else "displayName"
	if not payload.get(required_attribute):
		fail(f"{required_attribute} is required when creating a SCIM {args.resource[:-1]}")
	status, body = request_scim(args, "POST", args.resource, payload)
	record_created(args.resource)
	print_response(status, body)


def replace_resource(args):
	payload = build_user(args) if args.resource == "Users" else build_group(args)
	status, body = request_scim(args, "PUT", f"{args.resource}/{args.id}", payload)
	record_updated(args.resource)
	print_response(status, body)


def delete_resource(args):
	status, body = request_scim(args, "DELETE", f"{args.resource}/{args.id}")
	print_response(status, body)


def patch_resource(args):
	operations = [parse_json(value, "--operation") for value in args.operation]
	if not all(isinstance(operation, dict) for operation in operations):
		fail("Each --operation value must be a JSON object")
	payload = {"schemas": [SCIM_PATCH_SCHEMA], "Operations": operations}
	status, body = request_scim(args, "PATCH", f"{args.resource}/{args.id}", payload)
	record_updated(args.resource)
	print_response(status, body)


def update_resource(args):
	if args.method == "patch":
		if not args.operation:
			fail("--operation is required when --method patch is selected")
		patch_resource(args)
	else:
		replace_resource(args)


def set_active(args, active):
	args.operation = [json.dumps({"op": "replace", "path": "active", "value": active})]
	patch_resource(args)


def change_members(args, operation):
	value = [{"value": member} for member in args.member]
	args.operation = [json.dumps({"op": operation, "path": "members", "value": value})]
	patch_resource(args)


def add_connection_options(parser):
	parser.add_argument("--scim-token", help="Bearer token (overrides SCIM_TOKEN)")
	parser.add_argument("--app-env", choices=sorted(ENV_URL_VARIABLES), help="Target environment (overrides APP_ENV)")
	parser.add_argument("--scim-dev-url", help="DEV SCIM API base URL (overrides SCIM_DEV_URL)")
	parser.add_argument("--scim-prod-url", help="PROD SCIM API base URL (overrides SCIM_PROD_URL)")
	parser.add_argument(
		"--scim-email-domain",
		help="Email domain for usernames without @ (overrides SCIM_EMAIL_DOMAIN)",
	)
	parser.add_argument("--timeout", type=float, default=30, help="HTTP request timeout in seconds (default: 30)")


def add_list_arguments(parser):
	filters = parser.add_mutually_exclusive_group()
	filters.add_argument("--filter", help="SCIM filter, e.g. 'userName eq \"user@example.com\"'")
	filters.add_argument("--filter-name", help="Case-insensitive substring match on user family/given name or group display name")
	filters.add_argument("--filter-username", help="Case-insensitive substring match on userName (list-users only)")
	parser.add_argument("--start-index", type=int, help="1-based SCIM pagination start index")
	parser.add_argument("--count", type=int, help="Maximum resources to return")
	parser.add_argument("--attributes", help="Comma-separated SCIM attributes to return")
	parser.add_argument(
		"--format",
		choices=("names", "json", "csv"),
		default="names",
		help=(
			"Output format: names (default, human-readable list), json (raw SCIM response), "
			"or csv (spreadsheet-friendly with headers). Applies to both the terminal display "
			"and, if --export/--export-only is used, the exported file's contents."
		),
	)
	parser.add_argument("--show-members", action="store_true", help="For list-groups names output, show indented member names")
	export_options = parser.add_mutually_exclusive_group()
	export_options.add_argument("--export", metavar="FILENAME", help="Also write output to FILENAME, overwriting it if it exists")
	export_options.add_argument("--export-only", metavar="FILENAME", help="Write output only to FILENAME, overwriting it if it exists")


def add_user_arguments(parser, require_user_name=False):
	parser.add_argument("--user-name", required=require_user_name, help="Email address; required and unique for SCIM user creation")
	parser.add_argument("--given-name", help="name.givenName")
	parser.add_argument("--family-name", help="name.familyName")
	parser.add_argument("--display-name", help="User display name")
	parser.add_argument("--email", action="append", help="Email value; may be supplied multiple times")
	parser.add_argument("--primary-email", help="Primary email value (also adds it when --email is absent)")
	parser.add_argument("--active", action=argparse.BooleanOptionalAction, default=None, help="Set active or inactive")
	parser.add_argument("--external-id", help="Identity-provider externalId")
	parser.add_argument("--json", help="Complete SCIM User JSON object; overrides individual user attributes")


def add_group_arguments(parser, require_display_name=False):
	parser.add_argument("--display-name", required=require_display_name, help="Group displayName; required for SCIM group creation")
	parser.add_argument("--external-id", help="Identity-provider externalId")
	parser.add_argument("--member", action="append", help="Member user ID; may be supplied multiple times")
	parser.add_argument("--json", help="Complete SCIM Group JSON object; overrides individual group attributes")


def add_operation_parser(parent, command, help_text, example):
	command_prefix = f"{command} "
	if example.startswith(command_prefix):
		example = example[len(command_prefix):]
	return parent.add_parser(
		command,
		help=help_text,
		description=help_text,
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog=f"Example:\n  python3 %(prog)s {example}",
	)


def add_resource_commands(parent, singular, resource):
	plural = f"{singular}s"
	list_filter = 'userName eq "user@example.com"' if resource == "Users" else 'displayName eq "Engineering"'
	if resource == "Users":
		list_help = "List users, optionally filtered {--filter, --filter-name, --filter-username}, optionally formatted {--format names|json|csv}"
	else:
		list_help = "List groups, optionally filtered {--filter, --filter-name}, optionally formatted {--format names|json|csv, --show-members}"
	list_parser = add_operation_parser(
		parent, f"list-{plural}", list_help, f"list-{plural} --filter '{list_filter}'"
	)
	add_list_arguments(list_parser)
	list_parser.set_defaults(handler=list_resources, resource=resource)

	get_parser = add_operation_parser(parent, f"get-{singular}", f"Get one {singular}", f"get-{singular} --id {singular.upper()}_ID")
	get_parser.add_argument("--id", required=True, help=f"SCIM {singular.title()} ID")
	get_parser.add_argument("--attributes", help="Comma-separated SCIM attributes to return")
	get_parser.set_defaults(handler=get_resource, resource=resource)

	create_example = (
		"create-user --user-name user@example.com --given-name Ada --family-name Lovelace"
		if resource == "Users"
		else "create-group --display-name Engineering --member USER_ID"
	)
	create_parser = add_operation_parser(parent, f"create-{singular}", f"Create a {singular}", create_example)
	if resource == "Users":
		add_user_arguments(create_parser)
	else:
		add_group_arguments(create_parser)
	create_parser.set_defaults(handler=create_resource, resource=resource)

	update_example = (
		f"update-user --id USER_ID --method patch --operation '{{\"op\":\"replace\",\"path\":\"active\",\"value\":false}}'"
		if resource == "Users"
		else f"update-group --id GROUP_ID --method patch --operation '{{\"op\":\"add\",\"path\":\"members\",\"value\":[{{\"value\":\"USER_ID\"}}]}}'"
	)
	update_parser = add_operation_parser(parent, f"update-{singular}", f"Update a {singular} with PUT or PATCH", update_example)
	update_parser.add_argument("--id", required=True, help=f"SCIM {singular.title()} ID")
	update_parser.add_argument("--method", choices=("put", "patch"), default="put", help="Update method (default: put)")
	update_parser.add_argument("--operation", action="append", help='SCIM PatchOp JSON; required for --method patch')
	if resource == "Users":
		add_user_arguments(update_parser)
	else:
		add_group_arguments(update_parser)
	update_parser.set_defaults(handler=update_resource, resource=resource)

	delete_help = "Deactivate a user account" if resource == "Users" else "Remove a group"
	delete_parser = add_operation_parser(parent, f"delete-{singular}", delete_help, f"delete-{singular} --id {singular.upper()}_ID")
	delete_parser.add_argument("--id", required=True, help=f"SCIM {singular.title()} ID")
	delete_parser.set_defaults(handler=delete_resource, resource=resource)


def build_parser():
	parser = argparse.ArgumentParser(
		description="Manage OpenWebUI SCIM 2.0 users and groups.",
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog=HELP_EXAMPLES,
	)
	add_connection_options(parser)
	commands = parser.add_subparsers(dest="command", required=True, title="operations")
	add_resource_commands(commands, "user", "Users")
	add_resource_commands(commands, "group", "Groups")
	import_parser = add_operation_parser(
		commands, "import-groups", "Import action,group,userName CSV data; adds/drops group memberships, creating missing users and groups", "import-groups roster.csv"
	)
	import_parser.add_argument("filename", metavar="FILENAME", help="Path to a headerless CSV file with action,group,userName columns")
	import_parser.set_defaults(handler=import_groups)
	requirements_parser = add_operation_parser(
		commands, "requirements", "Report required fields for creating Users and/or Groups", "requirements --mode both"
	)
	requirements_parser.add_argument(
		"--mode", choices=("both", "users", "groups"), default="both", help="Which resource type(s) to report on (default: both)"
	)
	requirements_parser.set_defaults(handler=show_requirements)
	return parser


def main():
	parser = build_parser()
	args = parser.parse_args()
	args.handler(args)
	print_summary()


if __name__ == "__main__":
	main()
