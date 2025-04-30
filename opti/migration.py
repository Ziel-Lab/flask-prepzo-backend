"""
Migration script to help users migrate from the old structure to the new modular structure
"""
import os
import sys
import shutil
import logging
from pathlib import Path
import argparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("migration")

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Migrate from the old structure to the new modular structure"
    )
    parser.add_argument(
        "--backup", 
        action="store_true", 
        help="Create a backup before migration"
    )
    return parser.parse_args()

def create_backup(root_dir):
    """Create a backup of the current project"""
    backup_dir = root_dir / "backup"
    logger.info(f"Creating backup in {backup_dir}")
    
    # Ensure backup directory exists
    if not backup_dir.exists():
        backup_dir.mkdir(parents=True)
    
    # Backup key files
    files_to_backup = [
        "api.py",
        "agent.py",
        "conversation_manager.py",
        "knowledgebase.py",
        "prompts.py",
        "supabase_client.py",
        "server.py",
        "run_backend.py"
    ]
    
    for file in files_to_backup:
        file_path = root_dir / file
        if file_path.exists():
            shutil.copy2(file_path, backup_dir / file)
            logger.info(f"Backed up {file}")
    
    logger.info("Backup completed")

def update_imports(file_path):
    """Update imports in a file to use the new modular structure"""
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Map old imports to new imports
    replacements = {
        "from api import AssistantFnc": "from opti.agent.agent import PrepzoAgent",
        "from conversation_manager import ConversationManager": "from opti.data.conversation_manager import ConversationManager",
        "from knowledgebase import pinecone_search": "from opti.services.pinecone_service import PineconeService",
        "from prompts import INSTRUCTIONS, WELCOME_MESSAGE": "from opti.prompts.agent_prompts import AGENT_INSTRUCTIONS, WELCOME_MESSAGE",
        "import knowledgebase": "from opti.services import pinecone_service",
        "from supabase_client import SupabaseEmailClient": "from opti.data.supabase_client import SupabaseEmailClient",
        "server:asgi_app": "opti.server.app:asgi_app",
        "agent.py": "opti.agent"
    }
    
    for old, new in replacements.items():
        content = content.replace(old, new)
    
    with open(file_path, 'w') as f:
        f.write(content)
    
    logger.info(f"Updated imports in {file_path}")

def update_run_backend(run_backend_path, root_dir):
    """
    Update run_backend.py to use the new modular structure
    Either replace it with the new modular version or modify it
    """
    if not run_backend_path.exists():
        logger.warning(f"run_backend.py file not found at {run_backend_path}")
        return
    
    # Create a new modular run_backend.py
    new_content = """#!/usr/bin/env python
\"\"\"
Compatibility wrapper for running both server and agent processes
\"\"\"
from opti.runner import run_processes

def main():
    \"\"\"Run the application with both server and agent processes\"\"\"
    run_processes()

if __name__ == "__main__":
    main()
"""
    
    with open(run_backend_path, 'w') as f:
        f.write(new_content)
    
    logger.info(f"Updated {run_backend_path} to use the new modular structure")

def update_server(server_path, root_dir):
    """
    Update server.py to use the new modular structure
    Either replace it with a reference to the new structure or modify it
    """
    if not server_path.exists():
        logger.warning(f"Server file {server_path} not found")
        return
    
    # Create a new modular server.py
    new_content = """#!/usr/bin/env python
\"\"\"
Compatibility wrapper for the server
\"\"\"
from opti.server.app import asgi_app

# If running directly, start the server
if __name__ == "__main__":
    from opti.server.app import run_server
    run_server()
"""
    
    with open(server_path, 'w') as f:
        f.write(new_content)
    
    logger.info(f"Updated {server_path} to use the new modular structure")

def create_import_shortcut(root_dir):
    """Create a simple import shortcut file"""
    shortcut_path = root_dir / "run_prepzo.py"
    
    content = """#!/usr/bin/env python
\"\"\"
Main entry point for the Prepzo application
\"\"\"
from opti.runner import main

if __name__ == "__main__":
    main()
"""
    
    with open(shortcut_path, 'w') as f:
        f.write(content)
    
    logger.info(f"Created import shortcut at {shortcut_path}")

def main():
    """Run the migration script"""
    args = parse_args()
    root_dir = Path(__file__).parent.parent
    
    logger.info(f"Starting migration from old structure to new modular structure")
    logger.info(f"Root directory: {root_dir}")
    
    # Create backup if requested
    if args.backup:
        create_backup(root_dir)
    
    # Update server.py
    server_path = root_dir / "server.py"
    update_server(server_path, root_dir)
    
    # Update run_backend.py
    run_backend_path = root_dir / "run_backend.py"
    update_run_backend(run_backend_path, root_dir)
    
    # Update any other files that might import from the old structure
    for file_path in root_dir.glob("*.py"):
        if file_path.name not in ["run_prepzo.py", "server.py", "run_backend.py", "migration.py"] and file_path.name.endswith(".py"):
            update_imports(file_path)
    
    # Create import shortcut
    create_import_shortcut(root_dir)
    
    logger.info("Migration completed. You can now use the new modular structure.")
    logger.info("To run the application, use: python run_prepzo.py")

if __name__ == "__main__":
    main() 