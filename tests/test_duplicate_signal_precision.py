"""Concrete responsibility collisions versus shared infrastructure observations."""

import pytest
from pytest_readable import readable

from bpfw.core.catalog.scanner import scan_python_project
from bpfw.core.catalog.duplicate_profile import DuplicateProfileBuilder, DuplicateActiveProfileRule


def profile_findings(tmp_path, source):
    (tmp_path / "sample.py").write_text(source)
    scan = scan_python_project(tmp_path, ["."], [])
    blocks = [{"id": unit.symbol, "status": "active", "domain": "sample",
               "purpose": f"Perform the {unit.symbol} operation.",
               "code": {"path": unit.path, "symbol": unit.symbol, "kind": unit.symbol_type}}
              for unit in scan.discovered_units]
    profiles = DuplicateProfileBuilder(
        project_root=tmp_path, discovered_units=scan.discovered_units,
        source_repository=scan.source_repository, blocks=blocks,
    ).build()
    return DuplicateActiveProfileRule().validate(blocks, profiles)


@pytest.mark.parametrize("source", [
    "def list_orders(request):\n    return render(request, 'shared/form.html', {'orders': orders()})\n"
    "def edit_user(request):\n    return render(request, 'shared/form.html', {'user': user()})\n",
    "def accept_login(account):\n    logger.info('Login accepted', account)\n"
    "def create_client(client):\n    logger.info('Client created', client)\n",
    "def update_parser():\n    parser.add_argument('update')\n    return parser\n"
    "def main_command():\n    return dispatch('update')\n",
    "import subprocess\n"
    "def backup():\n    return subprocess.run(['podman', 'volume', 'export'])\n"
    "def start():\n    return subprocess.run(['podman', 'start', 'web'])\n",
    "def send_email(user):\n    send(user, 'Welcome')\n"
    "def send_sms(phone):\n    send(phone, 'Verification')\n",
    "def send_package(client, payload):\n    return client.post('/package', json=payload)\n"
    "def embed_query(client, query):\n    return client.post('/embeddings', json=query)\n",
])
@readable(
    intention="Keep shared infrastructure from becoming a hard responsibility collision.",
    steps=["Compare two operations sharing a template, logger, CLI word, executable or generic send call."],
    criteria=["Distinct operations do not produce a blocking duplicate profile."],
)
def test_shared_infrastructure_is_not_a_hard_duplicate(tmp_path, source):
    assert not any(finding.severity == "block" for finding in profile_findings(tmp_path, source))


@pytest.mark.parametrize("source", [
        "def export_orders(content):\n    destination = Path('exports/orders.json')\n    destination.write_text(content)\n"
        "def write_orders(content):\n    destination = Path('exports/orders.json')\n    destination.write_text(content.strip())\n",
        "def disable_account(cursor, identifier):\n    cursor.execute('UPDATE accounts SET enabled = 0 WHERE id = ?', (identifier,))\n"
        "def block_account(cursor, account):\n    cursor.execute('UPDATE accounts SET enabled = 0 WHERE id = ?', (account,))\n",
        "@router.post('/orders')\ndef create_order():\n    return create()\n"
        "@router.post('/orders')\ndef submit_order():\n    return submit()\n",
])
@readable(
    intention="Continue blocking concrete write and route ownership collisions.",
    steps=["Compare independent functions writing the same file or SQL target, or owning the same HTTP route."],
    criteria=["A strong duplicate profile still blocks each concrete responsibility collision."],
)
def test_same_concrete_resource_still_blocks(tmp_path, source):
    findings = profile_findings(tmp_path, source)
    assert any(finding.code == "DUPLICATE_ACTIVE_PROFILE" and finding.severity == "block" for finding in findings)
