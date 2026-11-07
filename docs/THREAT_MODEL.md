# RoleFit AI - Threat Model (v0.2)

Informed by OWASP Top 10 for LLM Applications 2025, OWASP API Security Top 10 and the NIST Generative AI Profile.
This is a technical design artefact, not a legal or compliance determination.

## Assets
Resumes/transcripts (HIGH), evidence records, profile & consents, credentials/JWT secret, audit log, scoring integrity.

## Trust boundaries
| Source | Trust |
|---|---|
| Authenticated user's own input | Authenticated, still validated (strict schemas) |
| Resume text, job descriptions, emails, web pages | **UNTRUSTED DATA, never instructions** |
| Model output (future) | Untrusted until schema + evidence validation |

## Threats and controls (with the test that proves each one)
| # | Threat | Control | Test |
|---|---|---|---|
| T1 | Direct/indirect prompt injection in job text/resume | Deterministic parser ignores instructions; `injection.scan` quarantines; `build_llm_context` refuses quarantined text and wraps data in fixed delimiters | `test_injection_scan_and_context_gate`, `test_job_injection_is_quarantined_not_obeyed` |
| T2 | Hidden white/zero-width text in resumes | DOCX scan flags `HIDDEN_TEXT_SUSPECTED`, zero-width counter | `test_hidden_text_flagged` |
| T3 | Broken object-level authorization (guessing IDs) | All reads via `get_owned(kind,id,owner_id)`; 404 on mismatch | `test_cross_user_isolation` |
| T4 | SSRF via job URL | https-only, domain allowlist, no IP literals/userinfo/ports, DNS result must be public (blocks metadata, loopback, private, IPv4-mapped); MVP never fetches | `test_ssrf_*`, `test_job_url_ssrf` |
| T5 | Malicious uploads (macros, polyglots, zip bombs, active PDF) | Extension allowlist, signature check, size cap, macro/active-content rejection, entry/ratio/size limits, EICAR hook | `test_upload_rejections`, `test_zip_bomb_rejected` |
| T6 | Unsupported/altered CV claims | Evidence-only drafting; metric and skill validators; export blocked until each bullet approved | `test_resume_blocks_unsupported_claims`, `test_resume_export_requires_...` |
| T7 | Silent inference of visa/language/graduation | Missing data -> `CONFIRMATION_REQUIRED`; conflicts surfaced, never resolved | `test_language_met_and_unknown_never_inferred`, `test_conflict_surfaced_not_resolved` |
| T8 | Credential stuffing / brute force | scrypt hashing, timing-equalised login, per-IP limit, per-account lockout | `test_registration_and_login_hardening` |
| T9 | Session theft/reuse | Short-lived JWT + server-side revocation | `test_logout_revokes_token` |
| T10 | Resource exhaustion | Request-size middleware, upload/job/score quotas, per-user API limit | `test_request_size_limit`, `test_upload_rate_limit` |
| T11 | Sensitive data in logs | Audit stores IDs/hashes only; long values hashed | `test_no_secrets_or_raw_text_in_audit` |
| T12 | Retention/erasure failure | Export + re-authenticated deletion, audit pseudonymisation | `test_export_and_deletion` |
| T14 | SSRF / abuse through the official-page fetcher | Consent required; every hop re-validated (https, allowlist, public DNS, no IP literals/ports/userinfo); max 3 redirects; 2 MB and 10 s caps; HTML-only; text extracted with stdlib parser, scripts dropped; fetched text goes through injection scan; per-user hourly quota | `test_fetch_*`, `test_jobs_fetch_endpoint` |
| T15 | Assessment cheating / leaked questions | Practice questions come only from RoleFit's own template bank and the candidate's evidence; generation refused when a live assessment is flagged | `test_practice_is_original_relevant_and_refuses_live_assessment` |
| T16 | Cross-user access to new objects (applications, companies, resumes) | Same owner-scoped data layer; 404 on mismatch; cascade delete of resumes with their job | `test_application_tracking_and_outcomes`, `test_list_get_delete_are_owner_scoped` |
| T17 | Weak/placeholder signing secret | API refuses the `.env.example` placeholder and secrets < 32 chars; setup script generates a random secret, `.env` is chmod 600 and git-ignored | `test_placeholder_jwt_secret_is_refused` |
| T18 | Automatic discovery abusing job boards or reaching internal hosts | Fixed API hosts (not user-configurable); board names restricted to `[A-Za-z0-9_.-]`; same SSRF/size/time controls; one fetch per board per cycle; consent required; injection scan on every posting | `tests/test_discovery.py` |
| T19 | Feeds/emails leaking data or carrying attacks | Only `https://www.google.com/alerts/feeds/<n>/<n>` accepted; no redirects; XML with DTD/entities rejected; only https target links kept; leads cannot become scored jobs without the full posting; emails carry titles/links/scores only, opt-in, SMTP credentials from env only | `test_google_alerts_feed_*`, `test_no_email_without_opt_in_*` |
| T13 | Untrusted text or PII reaching a model; model fabricating facts | `/explain` sends only code-generated structured facts (no job/resume text); gateway has provider allowlist, timeout, bounded retries, circuit breaker, token budget, strict schema; output rejected if it adds numbers or makes promises | `tests/test_llm.py` |

## Known residual risks (not yet mitigated)
- No application-level encryption at rest (rely on disk/DB encryption); no key management (`encryption_key_id` not implemented).
- Malware scanning is an EICAR stub; integrate ClamAV before real use.
- Rate limiter and lockout are in-process memory (not shared across instances).
- JWT HS256 with a single secret; no OIDC/MFA yet; no CSRF layer because Bearer tokens are used (a browser UI must store tokens in memory or httpOnly cookies, never localStorage).
- Regex injection detection is defence-in-depth only; a determined attacker can evade it. Real protection = no tool authority + deterministic parsing + human approval.
- PDF extraction path (pypdf) is not covered by tests.
- Fetcher validates DNS before connecting but does not pin the resolved IP, so a DNS-rebinding race is possible; mitigated by the
  domain allowlist. Pin the IP or use an egress proxy before wider use.
- The discovery scheduler runs inside the API process (single instance). Run one API instance, or move it to a separate worker before scaling out.
- Closed-posting detection is phrase-based and may miss some wording; the job's `last_checked` date is shown so stale data is visible.
- No admin/RBAC beyond a `role` column; no break-glass flow.
- LLM token budget is in-memory per process. Free-tier limits and data terms change; re-check the provider's terms before use.
