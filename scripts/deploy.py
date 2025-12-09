#!/usr/bin/env python3
"""
Deploy NexShift Agent to GCP Vertex AI Agent Engine.

This script handles the deployment of the nurse rostering agent to GCP.
Based on the rrd-console-adk deployment pattern.

Usage:
    python scripts/deploy.py deploy --project PROJECT_ID --location LOCATION
    python scripts/deploy.py delete --project PROJECT_ID --location LOCATION
    python scripts/deploy.py list --project PROJECT_ID --location LOCATION
"""

import argparse
import datetime
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_dependencies():
    """Check if required packages are installed."""
    try:
        import vertexai
        from vertexai import agent_engines
        print("✅ google-cloud-aiplatform installed")
    except ImportError:
        print("❌ Missing google-cloud-aiplatform. Install with:")
        print("   pip install 'google-cloud-aiplatform[agent_engines,adk]>=1.112'")
        sys.exit(1)

    try:
        from google.adk.agents import Agent
        print("✅ google-adk installed")
    except ImportError:
        print("❌ Missing google-adk. Install with:")
        print("   pip install google-adk")
        sys.exit(1)


def deploy_agent(
    project: str,
    location: str,
    agent_name: str = "nexshift-agent",
    requirements_file: str = None,
    extra_packages: list[str] = None,
    service_account: str = None,
):
    """Deploy the agent to Vertex AI Agent Engine."""
    import vertexai
    from vertexai import agent_engines
    from vertexai.preview.reasoning_engines import AdkApp

    # Import the root agent
    from agents.agent import root_agent

    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🏥 DEPLOYING NEXSHIFT AGENT TO VERTEX AI AGENT ENGINE   ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    print(f"   Project: {project}")
    print(f"   Location: {location}")
    print(f"   Agent Name: {agent_name}")

    # Set up staging bucket
    staging_bucket_uri = f"gs://{project}-nexshift-agent-staging"

    # Initialize Vertex AI
    print("\n📡 Initializing Vertex AI...")
    vertexai.init(project=project, location=location, staging_bucket=staging_bucket_uri)

    # Read requirements from file or use defaults
    if requirements_file and os.path.exists(requirements_file):
        with open(requirements_file) as f:
            requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        print(f"📋 Requirements loaded from {requirements_file}")
    else:
        # Use requirements.txt from project root
        req_path = PROJECT_ROOT / "requirements.txt"
        if req_path.exists():
            with open(req_path) as f:
                requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            print(f"📋 Requirements loaded from {req_path}")
        else:
            requirements = [
                "google-cloud-aiplatform[agent_engines,adk]>=1.112",
                "google-adk>=1.20.0",
                "google-genai>=1.53.0",
                "ortools>=9.14.6206",
                "pydantic>=2.12.5",
                "typing-extensions>=4.15.0",
            ]
            print("📋 Using default requirements")

    print(f"   Requirements: {requirements}")

    # Set up extra packages - include all local directories
    if extra_packages is None:
        extra_packages = [
            "./agents",
            "./tools",
            "./models",
            "./callbacks",
            "./utils",
            "./data",
        ]
    print(f"📦 Extra packages: {extra_packages}")

    # Create the AdkApp
    print("\n📦 Creating AdkApp...")
    agent_engine = AdkApp(agent=root_agent)

    # Agent configuration
    agent_config = {
        "agent_engine": agent_engine,
        "display_name": agent_name,
        "description": "NexShift Nurse Rostering Agent - AI-powered scheduling with OR-Tools optimization",
        "requirements": requirements,
        "extra_packages": extra_packages,
        "resource_limits": {
            "cpu": "8",
            "memory": "32Gi",
        },
    }

    if service_account:
        agent_config["service_account"] = service_account

    logger.info(f"Agent config: {agent_config}")

    # Check if an agent with this name already exists
    print("\n🔍 Checking for existing agent...")
    existing_agents = list(agent_engines.list(filter=f"display_name={agent_name}"))

    print("\n⏳ Deploying agent (this may take a few minutes)...")
    try:
        if existing_agents:
            # Update the existing agent
            print(f"   Found existing agent, updating: {agent_name}")
            remote_agent = existing_agents[0].update(**agent_config)
        else:
            # Create a new agent
            print(f"   Creating new agent: {agent_name}")
            remote_agent = agent_engines.create(**agent_config)

        print("\n✅ Deployment successful!")
        print(f"   Resource Name: {remote_agent.resource_name}")

        # Save deployment info
        deployment_info = {
            "resource_name": remote_agent.resource_name,
            "project": project,
            "location": location,
            "display_name": agent_name,
            "deployment_timestamp": datetime.datetime.now().isoformat(),
        }

        info_path = PROJECT_ROOT / "deployment_info.json"
        with open(info_path, "w") as f:
            json.dump(deployment_info, f, indent=2)
        print(f"   Deployment info saved to: {info_path}")

        return remote_agent

    except Exception as e:
        print(f"\n❌ Deployment failed: {e}")
        raise


def delete_agent(project: str, location: str, resource_name: str = None):
    """Delete a deployed agent from Agent Engine."""
    import vertexai
    from vertexai import agent_engines

    # Try to load deployment info if resource_name not provided
    if not resource_name:
        info_path = PROJECT_ROOT / "deployment_info.json"
        if info_path.exists():
            with open(info_path) as f:
                info = json.load(f)
                resource_name = info.get("resource_name")

    if not resource_name:
        print("❌ No resource name provided and no deployment_info.json found")
        sys.exit(1)

    print(f"\n🗑️  Deleting agent: {resource_name}")

    vertexai.init(project=project, location=location)

    try:
        agent = agent_engines.get(resource_name)
        agent.delete(force=True)
        print("✅ Agent deleted successfully!")

        # Remove deployment info file
        info_path = PROJECT_ROOT / "deployment_info.json"
        if info_path.exists():
            os.remove(info_path)
            print(f"   Removed {info_path}")

    except Exception as e:
        print(f"❌ Delete failed: {e}")
        raise


def list_agents(project: str, location: str):
    """List all deployed agents in the project."""
    import vertexai
    from vertexai import agent_engines

    print(f"\n📋 Listing agents in {project}/{location}")

    vertexai.init(project=project, location=location)

    try:
        agents = list(agent_engines.list())
        if not agents:
            print("   No agents found")
        else:
            for agent in agents:
                print(f"   - {agent.display_name}: {agent.resource_name}")
    except Exception as e:
        print(f"❌ Failed to list agents: {e}")


def test_agent(project: str, location: str, message: str = None, resource_name: str = None):
    """Test a deployed agent with a sample query."""
    import asyncio
    import vertexai
    from vertexai import agent_engines

    # Try to load deployment info if resource_name not provided
    if not resource_name:
        info_path = PROJECT_ROOT / "deployment_info.json"
        if info_path.exists():
            with open(info_path) as f:
                info = json.load(f)
                resource_name = info.get("resource_name")

    if not resource_name:
        print("❌ No resource name provided and no deployment_info.json found")
        sys.exit(1)

    print(f"\n🧪 Testing agent: {resource_name}")

    vertexai.init(project=project, location=location)

    test_message = message or "Show me the current nurse stats"
    print(f"   Message: {test_message}")

    async def run_test():
        agent = agent_engines.get(resource_name)
        print("\n📨 Response:")
        async for event in agent.async_stream_query(
            user_id="test-user",
            message=test_message,
        ):
            print(event)

    asyncio.run(run_test())


def main():
    parser = argparse.ArgumentParser(
        description="Deploy NexShift Agent to GCP Vertex AI Agent Engine"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy the agent")
    deploy_parser.add_argument("--project", "-p", required=True, help="GCP Project ID")
    deploy_parser.add_argument("--location", "-l", default="us-central1", help="GCP Location (default: us-central1)")
    deploy_parser.add_argument("--name", "-n", default="nexshift-agent", help="Display name for the agent")
    deploy_parser.add_argument("--requirements-file", "-r", help="Path to requirements.txt file")
    deploy_parser.add_argument("--extra-packages", nargs="+", help="Additional packages to include")
    deploy_parser.add_argument("--service-account", help="Service account email to use")

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a deployed agent")
    delete_parser.add_argument("--project", "-p", required=True, help="GCP Project ID")
    delete_parser.add_argument("--location", "-l", default="us-central1", help="GCP Location")
    delete_parser.add_argument("--resource", help="Agent resource name (or uses deployment_info.json)")

    # List command
    list_parser = subparsers.add_parser("list", help="List deployed agents")
    list_parser.add_argument("--project", "-p", required=True, help="GCP Project ID")
    list_parser.add_argument("--location", "-l", default="us-central1", help="GCP Location")

    # Test command
    test_parser = subparsers.add_parser("test", help="Test a deployed agent")
    test_parser.add_argument("--project", "-p", required=True, help="GCP Project ID")
    test_parser.add_argument("--location", "-l", default="us-central1", help="GCP Location")
    test_parser.add_argument("--resource", help="Agent resource name (or uses deployment_info.json)")
    test_parser.add_argument("--message", "-m", help="Test message to send")

    # Check command
    subparsers.add_parser("check", help="Check dependencies")

    args = parser.parse_args()

    if args.command == "check":
        check_dependencies()
        print("\n✅ All dependencies installed!")

    elif args.command == "deploy":
        check_dependencies()
        deploy_agent(
            project=args.project,
            location=args.location,
            agent_name=args.name,
            requirements_file=args.requirements_file,
            extra_packages=args.extra_packages,
            service_account=args.service_account,
        )

    elif args.command == "delete":
        delete_agent(
            project=args.project,
            location=args.location,
            resource_name=args.resource,
        )

    elif args.command == "list":
        list_agents(args.project, args.location)

    elif args.command == "test":
        test_agent(
            project=args.project,
            location=args.location,
            message=args.message,
            resource_name=args.resource,
        )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
