# Root supporting reads after independent initial

Fresh full read: `scripts/tests/test_install_hooks.py`. Its five tests inspect installer text; they do not install or execute the generated hooks. The claim that every real push exercises installation is a source assertion, not an execution receipt. Its broad `exit 1` substring does not bind failure handling to a particular branch; truncate-write assertion validates that text, not safe preservation of pre-existing hooks.

Fresh partial reads:

- `scripts/handlers/post_tool/reviewer.py:126-285`: DAG maps flow/class paths to mermaid-validate.py, with downstream checks for flow. Some other validators are project-owned scripts. This range includes DAG/config and start of content-hash helper, not subprocess execution or full invocation closure.
- `settings.json:319-349`: FileChanged is registered to an absolute Windows Python script path with timeout5, while statusLine points to cli/hud.py rather than context-bar.sh. Thus the old Bash status line's risks are not automatically current registered statusLine behavior. This slice also contains adjacent notification/plugin configuration, not a full settings review.

Text search found potential further supports in session/init.py watchPaths, reviewer.py run_spec_verification, import_graph.py/test_import_graph.py, Java testing skill, README and guide. Search results do not count as body reads. All unlisted ranges remain unread in this pass. Original execution/import remains zero. Actual Claude initial process is still pending; no response has been read and no joint conclusion has been made.
