# NFM Security Audit Review Report

## Execution Time
2026-06-29 02:15

## Agent Output Overview
- New test files: 6 (conftest.py + 5 test_*.py)
- New test cases: 31 (from 4 to 35, all passing)
- Security issues found: 5 (High 2 / Medium 2 / Low 1)
- Security issues fixed: 5
- New security module: 1 (backend/scripts/url_security.py)
- Modified code files: 11 (8 routers + 3 scripts)

## Verification Results

| # | Check Item | Result | Notes |
|---|-----------|--------|-------|
| A1 | SECURITY_AUDIT.md exists | PASS | 4842 bytes, complete content |
| A2 | Covers 9 audit dimensions | PASS | path traversal/SSRF/unauthorized access/session security/file ops/input validation/password security/CORS/sensitive info leak all covered |
| A3 | Severity level markers | NOTE | Report uses descriptive text instead of emoji markers, but each dimension has clear fix status and residual risk notes |
| B4 | pytest passes | PASS | 35 passed in 8.15s, exit code 0 |
| B5 | Test count meets minimum | PASS | From 4 to 35 (31 new), far exceeds minimum of 10 |
| B6 | Tests have real assertions | PASS | 114 assert statements across 6 test files, not stub tests |
| C7 | AI/ original files unmodified | PASS | 6 files MD5 hashes match baseline exactly; git diff only shows SECURITY_AUDIT.md added |
| C8 | backend/scripts/ no relative imports | PASS | grep for relative imports returned nothing |
| C9 | py_compile check | PASS | exit code 0, all .py files compile |
| D10 | Security fixes reasonable | PASS | See detailed analysis below |

## Security Findings Summary

### Fixed Issues

1. [HIGH] SSRF - /api/download/start accepted arbitrary items[].url; scan and page-size probes also made HEAD/Range requests to Notion external URLs. Fix: new url_security.py module - only http/https, rejects embedded credentials, rejects localhost/.local/private/loopback/link-local/reserved addresses, DNS resolution re-check, redirect target re-check. Integrated into download.py, scripts/download.py, scripts/notion.py, scripts/page_size_update.py.

2. [HIGH] Upload session path traversal - /api/upload/start trusted session_id directly, authenticated users could pass any server directory. Fix: new _validated_upload_session() only accepts STAGING_DIR/upload-* direct subdirectories.

3. [MEDIUM] Password comparison - login used plain string == comparison, timing attack risk. Fix: changed to secrets.compare_digest() with password length limit 1-1024.

4. [MEDIUM] Input validation - multiple routes lacked Pydantic boundaries (thread counts, array lengths, string lengths, config values). Fix: added extra=forbid, Field(min_length, max_length), Field(ge, le) to auth/settings/scan/download/upload/tools/system routes.

5. [LOW] Session security - SessionMiddleware used default cookie name, no expiry, https_only fixed False. Fix: dedicated cookie name nfm_session, max_age=86400, NFM_SESSION_HTTPS_ONLY env switch.

### Residual Risks (documented in report)

1. Single-tenant model: authenticated users can access global Notion Token (by design)
2. DNS rebinding race: pre-request IP check but no connection pinning to verified IP
3. notion_token visible to authenticated users (single-tenant settings page requirement)
4. CSRF: Session cookie auth POST endpoints lack CSRF token, SameSite=Lax mitigates

## Test Coverage Summary

| Test File | Tests | Assertions | Coverage |
|-----------|-------|------------|----------|
| test_auth_settings_version_notices.py | 6 | 18 | auth login/logout, settings GET/PUT, version, notices |
| test_scan_download_upload_routes.py | 7 | 20 | scan start/progress, download start (SSRF/input validation), upload start (path validation) |
| test_scripts_core.py | 8 | 16 | scripts/download, upload, notion extraction, page_size_update, migrate, batch_rename |
| test_staging_taskregistry.py | 5 | 13 | staging new_task_dir/zip_dir/cleanup, taskregistry register/detail/cancel |
| test_tools_tasks_system_routes.py | 5 | 36 | tools batch-rename/page-size, tasks list/detail/cancel, system restart/cleanup |
| test_smoke.py | 4 | 11 | original smoke tests (unchanged) |

## Code Changes Detail

### New Files
- backend/scripts/url_security.py - SSRF protection module
- backend/tests/conftest.py - test fixtures
- backend/tests/test_auth_settings_version_notices.py - auth/settings/version/notices route tests
- backend/tests/test_scan_download_upload_routes.py - scan/download/upload route tests
- backend/tests/test_scripts_core.py - scripts core module tests
- backend/tests/test_staging_taskregistry.py - staging + taskregistry tests
- backend/tests/test_tools_tasks_system_routes.py - tools/tasks/system route tests
- AI/SECURITY_AUDIT.md - security audit report

### Modified Files (11)
- backend/app/main.py - Session security enhancement
- backend/app/routers/auth.py - secrets.compare_digest + password length limit
- backend/app/routers/download.py - DownloadItem Pydantic model + URL safety check
- backend/app/routers/scan.py - Pydantic input boundaries
- backend/app/routers/settings.py - Pydantic input boundaries + notion_base_url safety check
- backend/app/routers/system.py - Pydantic input boundaries
- backend/app/routers/tools.py - Pydantic input boundaries
- backend/app/routers/upload.py - _validated_upload_session path validation + Pydantic boundaries
- backend/scripts/download.py - integrated safe_urlopen/safe_urlretrieve
- backend/scripts/notion.py - integrated safe_requests_head
- backend/scripts/page_size_update.py - integrated safe_requests_head

## Conclusion
PASSED

All verification items passed (1 format note: audit report uses descriptive text instead of emoji severity markers, but content is complete with clear fix status per dimension). Changes committed (commit: 9467c1b).
