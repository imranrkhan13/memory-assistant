
"""Personal Memory Assistant CLI — Phases 0 through 5."""
from .config import load_env
load_env()
import argparse
from .ai import process_note, answer_question
from .gemini import GeminiError
from .storage import (
    add_note,
    init_db,
    list_audit_log,
    list_facts,
    list_notes,
)
from .pipeline import (
    extract_note,
    pending_facts,
    prepare_schema,
)
from .providers import MockProvider
from .retrieval import ask
from .updates import fact_history, resolve_update
from .forget import (
    forget_fact,
    is_forgotten,
    prepare_forget_schema,
)


def main():
    parser = argparse.ArgumentParser(
        prog="memory_assistant",
        description="Private local personal memory assistant",
    )

    commands = parser.add_subparsers(dest="command")

    commands.add_parser("hello")
    commands.add_parser("init")
    commands.add_parser("notes")
    commands.add_parser("facts")
    commands.add_parser("pending")
    commands.add_parser("audit")

    server_command = commands.add_parser("serve")
    server_command.add_argument(
        "--port",
        type=int,
        default=8765,
    )

    add = commands.add_parser("add")
    add.add_argument("text")

    approve = commands.add_parser("approve")
    approve.add_argument("id", type=int)

    reject = commands.add_parser("reject")
    reject.add_argument("id", type=int)

    edit = commands.add_parser("edit")
    edit.add_argument("id", type=int)
    edit.add_argument("statement")

    question = commands.add_parser("ask")
    question.add_argument("question")

    history = commands.add_parser("history")
    history.add_argument("subject")

    forget = commands.add_parser("forget")
    forget.add_argument("fact_id", type=int)

    args = parser.parse_args()

    if args.command == "hello":
        print("Personal Memory Assistant is running.")
        return

    if args.command is None:
        parser.print_help()
        return

    if args.command == "serve":
        from .web import serve

        if not 1 <= args.port <= 65535:
            parser.error("Port must be between 1 and 65535.")

        serve(port=args.port)
        return

    init_db()
    prepare_schema()
    prepare_forget_schema()

    if args.command == "init":
        print("SQLite database initialized.")

    elif args.command == "add":
        try:
            if is_forgotten(args.text):
                raise ValueError(
                    "This exact note was previously forgotten."
                )

            note_id = add_note(args.text)
            print(f"Note saved. ID: {note_id}")

            results = process_note(note_id)

            if not results:
                print("SAMPLE: No matching extraction fixture.")

            for status, fact_id in results:
                print(f"SAMPLE: Fact #{fact_id}: {status}")

        except ValueError as error:
            print(f"Error: {error}")

    elif args.command == "notes":
        notes = list_notes()

        if not notes:
            print("No notes available.")

        for note in notes:
            print(f"[{note['id']}] {note['raw_text']}")

    elif args.command == "facts":
        facts = list_facts()

        if not facts:
            print("No facts available yet.")

        for fact in facts:
            print(
                f"SAMPLE [{fact['id']}] "
                f"{fact['statement']} | {fact['status']}"
            )

    elif args.command == "pending":
        pending = pending_facts()

        if not pending:
            print("No pending approvals.")

        for fact in pending:
            print(
                f"SAMPLE approval #{fact['approval_id']}: "
                f"{fact['statement']} ({fact['reason']})"
            )

    elif args.command in ("approve", "reject", "edit"):
        try:
            decision = (
                "rejected"
                if args.command == "reject"
                else "approved"
            )

            edited = (
                args.statement
                if args.command == "edit"
                else None
            )

            result = resolve_update(
                args.id,
                decision,
                edited,
            )

            print(
                f"SAMPLE: Approval #{args.id} "
                f"{result['decision']}."
            )

        except ValueError as error:
            print(f"Error: {error}")

    elif args.command == "ask":
        try:
            result = answer_question(args.question)
        except (GeminiError, ValueError) as error:
            print(f"AI request failed: {error}")
            return

        print(f"SAMPLE Answer: {result['answer']}")
        print(f"Validation: {result['validation']}")

        for source in result["sources"]:
            print(
                f"Source Note #{source['note_id']} "
                f"({source['date']}): "
                f"{source['text']}"
            )

        context = result["context"]

        print(
            f"Context: {context['characters']}"
            f"/{context['budget']} characters"
        )
        print(
            f"Included fact IDs: {context['included']}"
        )
        print(
            f"Dropped fact IDs: {context['dropped']}"
        )

    elif args.command == "history":
        rows = fact_history(args.subject)

        if not rows:
            print("No history found.")

        for row in rows:
            print(
                f"SAMPLE Fact #{row['id']}: "
                f"{row['statement']} "
                f"| status={row['status']} "
                f"| superseded_by={row['superseded_by']} "
                f"| source_note={row['note_id']}"
            )

    elif args.command == "forget":
        try:
            result = forget_fact(args.fact_id)

            print(
                f"Forgot fact #{result['forgotten_fact_id']}."
            )
            print(
                f"Removed source note "
                f"#{result['removed_note_id']}."
            )
            print(
                f"Removed {result['removed_facts']} "
                f"associated fact(s)."
            )

        except (ValueError, GeminiError) as error:
            print(f"Error: {error}")

    elif args.command == "audit":
        for event in list_audit_log():
            print(
                f"[{event['id']}] {event['action']} "
                f"{event['entity_type']} #{event['entity_id']}"
            )


if __name__ == "__main__":
    main()
