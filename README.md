# Open WebUI SCIM Admin

Developed by Nathan I Keiter, Gettysburg College.

`owui_scim_admin.py` is a command-line utility for administering [Open WebUI](https://github.com/open-webui/open-webui)
users and groups through its SCIM 2.0 API. It supports listing, retrieving,
creating, updating, and deleting users and groups; exporting list results; and
bulk-importing group memberships from a CSV file.

The script uses only the Python standard library. Set the SCIM API base URL
for each environment using these environment variables:

| Environment | Variable |
| --- | --- |
| `dev` | `SCIM_DEV_URL` |
| `prod` | `SCIM_PROD_URL` |

Set each variable to the full SCIM API base URL for the corresponding
deployment, including its SCIM version path (for example,
`https://scim-dev.example.com/api/v1/scim/v2`). Select the target with
`APP_ENV=dev` or `APP_ENV=prod`. The script requires the matching URL variable
to be set and no longer embeds organization-specific endpoints.

## Requirements and configuration

- Python 3.9 or later.
- An Open WebUI deployment with SCIM 2.0 enabled and reachable.
- A SCIM token and permission to perform the requested operations.
- The SCIM script can be run from any machine that has the required network
  access to the Open WebUI SCIM-enabled server.

Set the environment and token before running a command:

```sh
export APP_ENV=dev
export SCIM_DEV_URL='https://scim-dev.example.com/api/v1/scim/v2'
export SCIM_PROD_URL='https://scim.example.com/api/v1/scim/v2'
export SCIM_TOKEN='your-scim-token'
export SCIM_EMAIL_DOMAIN='example.com'  # only needed for bare usernames
python3 owui_scim_admin.py list-users
```

Every configuration environment variable can instead be supplied with its
command-line option. Pass global configuration options before the command:

```sh
python3 owui_scim_admin.py \
  --scim-token 'your-scim-token' \
  --app-env dev \
  --scim-dev-url 'https://scim-dev.example.com/api/v1/scim/v2' \
  --scim-prod-url 'https://scim.example.com/api/v1/scim/v2' \
  --scim-email-domain example.com \
  list-users
```

| Environment variable | Command-line option | Required |
| --- | --- | --- |
| `SCIM_TOKEN` | `--scim-token` | Yes, for every API operation. |
| `APP_ENV` | `--app-env {dev,prod}` | Yes; selects the endpoint. |
| `SCIM_DEV_URL` | `--scim-dev-url` | Required when the selected environment is `dev`. |
| `SCIM_PROD_URL` | `--scim-prod-url` | Required when the selected environment is `prod`. |
| `SCIM_EMAIL_DOMAIN` | `--scim-email-domain` | Required only when a username has no `@` and needs an email domain. |

When both are supplied, a command-line option overrides its environment
variable. The endpoint URLs are full SCIM API base URLs, including the SCIM
version path. `--timeout` sets the HTTP request timeout in seconds (default:
30). Avoid passing real tokens on shared command lines because they may be
recorded in shell history or process listings.

**Authentication implementation note:** The current source validates that a
token is configured, but its request headers contain a literal
`Authorization: ******` placeholder rather than sending that token. Replace
the placeholder with the authentication format required by your SCIM
deployment before using the script against a live API. Do not put real tokens
in source control or shared command history.

## Commands

Run `python3 owui_scim_admin.py --help` for the complete usage output. Each
command requires a SCIM token and target environment, supplied through either
the corresponding environment variables or command-line options above.

### Users

| Command | Purpose |
| --- | --- |
| `list-users` | List users; supports SCIM filtering, local substring filters, pagination, output formats, and export. |
| `get-user --id USER_ID` | Retrieve one user by SCIM ID. |
| `create-user` | Create a user using individual options or a complete JSON object. |
| `update-user --id USER_ID` | Replace a user with `--method put` (the default), or apply SCIM PatchOp operations with `--method patch`. |
| `delete-user --id USER_ID` | Send a SCIM DELETE request for the user. |

User creation/update options include `--user-name`, `--given-name`,
`--family-name`, `--display-name`, `--email` (repeatable), `--primary-email`,
`--active`/`--no-active`, and `--external-id`. Supplying `--json` provides a
complete SCIM User object and takes precedence over the individual attributes.
`--user-name` is required for creation.

For example:

```sh
python3 owui_scim_admin.py list-users --filter 'userName eq "ada@example.com"'
python3 owui_scim_admin.py list-users --filter-name "lovelace" --format csv --export users.csv
python3 owui_scim_admin.py create-user \
  --user-name ada@example.com --given-name Ada --family-name Lovelace
python3 owui_scim_admin.py update-user --id USER_ID --method patch \
  --operation '{"op":"replace","path":"active","value":false}'
```

The script derives a user name and email when constructing a user payload:
`--user-name ada@example.com` becomes `userName: "ada"` with that address as
the primary email. A value without `@` is used as the user name and receives
the email domain configured in `SCIM_EMAIL_DOMAIN`; set this variable to your
organization's email domain when using bare usernames. If it is unset, use a
complete email address instead. The same rule applies to values in the
`import-groups` CSV. During CSV imports, rows with a bare username and no
configured default domain are skipped. Valid rows continue to be processed;
afterward, the command exits with an error listing the skipped CSV row numbers
and usernames. If every non-empty row is skipped, the command exits before
making SCIM requests.

### Groups

| Command | Purpose |
| --- | --- |
| `list-groups` | List groups, with optional name/SCIM filtering, member display, and export. |
| `get-group --id GROUP_ID` | Retrieve one group by SCIM ID. |
| `create-group` | Create a group using options or a complete JSON object. |
| `update-group --id GROUP_ID` | Replace a group with PUT (default), or apply SCIM PatchOp operations with PATCH. |
| `delete-group --id GROUP_ID` | Send a SCIM DELETE request for the group. |

Group options include `--display-name`, `--external-id`, and repeatable
`--member USER_ID` values. `--json` accepts a complete SCIM Group object.
Creating a group requires `--display-name` unless a JSON object is provided.

For example:

```sh
python3 owui_scim_admin.py list-groups --filter-name "engineering" --show-members
python3 owui_scim_admin.py create-group --display-name Engineering --member USER_ID
python3 owui_scim_admin.py update-group --id GROUP_ID --method patch \
  --operation '{"op":"add","path":"members","value":[{"value":"USER_ID"}]}'
```

### Listing, filtering, and export

Both list commands support:

- `--filter`: pass a SCIM filter to the server.
- `--filter-name`: case-insensitive substring search on user given/family name
  or group display name. This is performed locally after retrieving results.
- `--filter-username`: case-insensitive local substring search on user name
  (`list-users` only).
- `--start-index`, `--count`, and `--attributes`: pagination/attribute options.
- `--format names|json|csv`: choose human-readable names (default), JSON, or
  CSV output.
- `--export FILE`: write the same output shown in the terminal to a file.
- `--export-only FILE`: write to a file without printing the list.
- `--show-members`: for `list-groups --format names`, include indented member
  names. This fetches user records to resolve member IDs.

CSV user output has `id`, `userName`, `givenName`, `familyName`, and `active`
columns. CSV group output has `id`, `displayName`, and `memberCount`. Export
files are overwritten if they already exist.

### Bulk group membership import

`import-groups FILE.csv` reads a headerless CSV. Each non-empty row must contain:

```text
action,group,userName
```

`action` must be `add` or `drop`; additional columns are ignored. Example:

```csv
add,Engineering,ada@example.com
add,Engineering,grace@example.com
drop,Engineering,alan@example.com
add,Research,grace@example.com
```

The import matches existing users by user name or email and groups by display
name, case-insensitively. Missing groups and users referenced by `add` rows are
created, then requested memberships are added or removed. New users are
activated, use the local part as `userName` when the CSV value is an email, and
use `SCIM_EMAIL_DOMAIN` as the derived email domain when a value has no `@`.
CSV rows without an email domain are skipped when `SCIM_EMAIL_DOMAIN` or
`--scim-email-domain` is not set; the final error identifies each skipped row.
Membership changes are skipped when the requested state is already present.
The command prints a count of created/updated resources and membership changes.

```sh
python3 owui_scim_admin.py --app-env dev import-groups roster.csv
```

The fake-data [scim-import-example.csv](examples/scim-import-example.csv) in
[`examples/`](examples/) is a template for this `import-groups` method. Replace
the sample group names and user names with your own, then review the rows and
target environment before importing. `add` rows can create missing users and
groups; `drop` rows change existing memberships.

Review the CSV and target environment before importing: this command creates
resources and changes group memberships in the target service.

The [env-example.txt](examples/env-example.txt) in [`examples/`](examples/) is
a generic reference for setting `APP_ENV` and `SCIM_TOKEN` and optionally
setting the DEV/PROD endpoint URLs and `SCIM_EMAIL_DOMAIN`. Adapt its values
to your environment and set them in your shell or deployment environment
before running the script; the script does not automatically load the text
file.

### Discover required SCIM fields

`requirements` attempts to report fields required to create Users and/or Groups:

```sh
python3 owui_scim_admin.py requirements --mode both
python3 owui_scim_admin.py requirements --mode users
```

It does so by sending an empty create request and inspecting the API's
validation response. If the API unexpectedly accepts an empty request, the
script attempts to delete the created resource. Use this command with care and
check the target service afterward.

## Error handling and output

Successful resource responses are printed as formatted JSON; empty responses
print the HTTP status. List operations print the selected list format. API HTTP
errors include the response details, and connection failures are reported with
an error message and exit status 2. Create/update operations also contribute to
a summary printed at the end of the command.

## Security

This tool can create, modify, and delete accounts and groups. Use a
least-privilege SCIM token, confirm `APP_ENV` before running mutations, and
avoid sharing exported user data or token values. The script does not include
a dry-run mode for CRUD commands or CSV imports.

## Related work

This is a stand-alone project and does not depend on the other projects below.
It is built for [Open WebUI](https://github.com/open-webui/open-webui); thank
you to its authors and contributors.

### Other related work by this author

- [owui-token-usage-tracking-plugin](https://github.com/nkeiter/owui-token-usage-tracking-plugin):
  Open WebUI filter plugin that tracks and limits token usage by tier.
- [owui-token-usage-admin](https://github.com/nkeiter/owui-token-usage-admin):
  command-line tool for managing token usage tiers and limits.
- [owui-token-usage-management-console](https://github.com/nkeiter/owui-token-usage-management-console):
  graphical (web) version of the token usage admin CLI.

## Disclaimer

The software is provided “AS IS,” without warranty of any kind, as stated in
the MIT License. To the fullest extent permitted by applicable law, Gettysburg
College, its trustees, officers, employees, and contributors disclaim liability
for claims, damages, or other liability arising from, out of, or in connection
with the software or its use. Use and deploy the software at your own risk;
operators are responsible for validating its behavior, security, SCIM
permissions, and compliance with their policies. This notice supplements but
does not replace the MIT License. Have counsel review the disclaimer for your
jurisdiction if a specific legal outcome is required.
