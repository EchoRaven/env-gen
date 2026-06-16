#!/usr/bin/env python3
"""
Knowledge CLI - Command-line interface for the knowledge system.

Usage:
    python -m multi_agent.knowledge.cli seed        # Seed initial knowledge
    python -m multi_agent.knowledge.cli search "query"  # Search knowledge
    python -m multi_agent.knowledge.cli list        # List all knowledge
    python -m multi_agent.knowledge.cli stats       # Show statistics
    python -m multi_agent.knowledge.cli export path.json  # Export to JSON
"""

import sys
import json
import argparse
from .store import KnowledgeStore
from .types import KnowledgeQuery
from .seed_data import seed_knowledge


def main():
    parser = argparse.ArgumentParser(description="Knowledge Management CLI")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Seed command
    seed_parser = subparsers.add_parser("seed", help="Seed initial knowledge")
    
    # Search command
    search_parser = subparsers.add_parser("search", help="Search knowledge")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-n", "--limit", type=int, default=5, help="Max results")
    search_parser.add_argument("-c", "--category", help="Filter by category")
    
    # List command
    list_parser = subparsers.add_parser("list", help="List knowledge")
    list_parser.add_argument("-c", "--category", help="Filter by category")
    list_parser.add_argument("-n", "--limit", type=int, default=20, help="Max entries")
    
    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Show statistics")
    
    # Export command
    export_parser = subparsers.add_parser("export", help="Export to JSON")
    export_parser.add_argument("path", help="Output file path")
    
    # Import command
    import_parser = subparsers.add_parser("import", help="Import from JSON")
    import_parser.add_argument("path", help="Input file path")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    store = KnowledgeStore(db_url=KnowledgeStore.default_sqlite_url())
    
    if args.command == "seed":
        count = seed_knowledge(store)
        print(f"✅ Seeded {count} knowledge entries")
        stats = store.get_stats()
        print(f"   Total entries: {stats['total_entries']}")
        print(f"   By category: {json.dumps(stats['by_category'], indent=2)}")
    
    elif args.command == "search":
        from .types import KnowledgeCategory
        
        query = KnowledgeQuery(
            query=args.query,
            category=KnowledgeCategory(args.category) if args.category else None,
            limit=args.limit
        )
        results = store.search(query)
        
        if not results:
            print("❌ No results found")
            return
        
        print(f"Found {len(results)} results:\n")
        for i, r in enumerate(results, 1):
            print(f"{'='*60}")
            print(f"[{i}] {r.knowledge.title}")
            print(f"    Score: {r.score:.2f} | Match: {r.match_type}")
            print(f"    Category: {r.knowledge.category.value}")
            if r.snippet:
                print(f"    Snippet: {r.snippet[:100]}...")
            print()
            print(r.knowledge.to_agent_prompt())
            print()
    
    elif args.command == "list":
        from .types import KnowledgeCategory
        
        if args.category:
            entries = store.list_by_category(KnowledgeCategory(args.category), args.limit)
        else:
            entries = store.list_all(args.limit)
        
        print(f"Found {len(entries)} entries:\n")
        for k in entries:
            print(f"• [{k.category.value}] {k.title}")
            print(f"  Severity: {k.severity.value} | Uses: {k.usage_count}")
            if k.summary:
                print(f"  {k.summary[:80]}...")
            print()
    
    elif args.command == "stats":
        stats = store.get_stats()
        print("📊 Knowledge Base Statistics\n")
        print(f"Total entries: {stats['total_entries']}")
        print(f"Semantic search: {'✅ enabled' if stats['has_semantic_search'] else '❌ disabled'}")
        print(f"\nBy category:")
        for cat, count in sorted(stats['by_category'].items()):
            print(f"  {cat}: {count}")
        print(f"\nMost used:")
        for item in stats['top_used'][:5]:
            print(f"  {item['title']}: {item['count']} uses")
    
    elif args.command == "export":
        store.export_json(args.path)
        print(f"✅ Exported to {args.path}")
    
    elif args.command == "import":
        count = store.import_json(args.path)
        print(f"✅ Imported {count} entries from {args.path}")


if __name__ == "__main__":
    main()

