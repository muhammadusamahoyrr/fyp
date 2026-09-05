# Why `--test-force-exit`

`mod_documents_dom.test.mjs` mounts the real `ModDocuments` inside jsdom. React's
scheduler and jsdom between them keep handles open after the tree unmounts and
the window is closed — two `Timeout` handles survive every attempt to track and
clear them, because they are captured during module initialisation, before any
override a test file can install.

Every test in that file passes; the process simply does not exit, and the runner
reports the FILE as failed at its timeout. `--test-force-exit` is Node's
supported answer to exactly that.

It does not mask assertion failures: results are reported before exit, and a
failing test still fails. It would mask a test that hangs forever, so if a file
starts timing out, check it is the environment holding handles and not the test
waiting on something that will never arrive.
