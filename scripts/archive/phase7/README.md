# Historical one-time patches

These seven scripts rewrote source/test files during the original Phase 7 work. They are not runtime modules, database migrations or test entry points, and no application/test code imports them. Their changes are already present in the application. They have been moved unchanged from the repository root to preserve project history.

Do not run them against the current application: their string replacements target historical source versions and can fail or overwrite newer work. Start the application and run tests using the root README commands instead.
