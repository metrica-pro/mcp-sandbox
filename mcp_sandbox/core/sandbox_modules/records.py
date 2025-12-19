from typing import List, Optional, Dict, Any
from mcp_sandbox.utils.config import logger


class SandboxRecordsMixin:
    def list_sandboxes(self) -> list:
        """Lists all sandbox containers"""
        sandboxes = []
        for sandbox in self.sandbox_client.containers.list(
            all=True, filters={"label": "python-sandbox"}
        ):
            sandbox_info = {
                "sandbox_id": sandbox.id,
                "name": sandbox.name,
                "status": sandbox.status,
                "image": sandbox.image.tags[0]
                if sandbox.image.tags
                else sandbox.image.short_id,
                "created": sandbox.attrs["Created"],
                "last_used": self.sandbox_last_used.get(sandbox.id),
            }
            sandboxes.append(sandbox_info)
        return sandboxes

    def list_user_sandboxes(
        self, user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Lists all sandboxes belonging to a user with additional information

        Args:
            user_id: The ID of the user whose sandboxes to list. If None, uses first user in DB

        Returns:
            List of sandbox info dictionaries
        """
        # Import here to avoid circular imports
        from mcp_sandbox.db.database import db

        if not user_id:
            # For debugging/testing - use first user
            all_users = db.get_all_users()
            if all_users:
                user_id = all_users[0].get("id")
                logger.info(f"Fallback to first user: {user_id}")
            else:
                return []

        logger.info(f"Listing sandboxes for user_id: {user_id}")

        # Get user's sandboxes from database
        user_sandboxes = db.get_user_sandboxes(user_id)
        logger.info(f"Found {len(user_sandboxes)} sandboxes in database for user")

        # Return directly from database if available
        if user_sandboxes:
            # Filter results, only return sandbox_id, name and installed_packages
            filtered_sandboxes = []

            for sandbox in user_sandboxes:
                # Create a new simplified sandbox record
                filtered_sandbox = {
                    "sandbox_id": sandbox["id"],
                    "name": sandbox["name"],
                    "installed_packages": [],
                }

                # Get installed packages
                try:
                    packages = self.list_installed_packages(sandbox["id"])
                    if packages:
                        filtered_sandbox["installed_packages"] = packages
                except Exception as e:
                    logger.error(
                        f"Error listing packages for sandbox {sandbox['id']}: {e}"
                    )

                filtered_sandboxes.append(filtered_sandbox)

            return filtered_sandboxes

        return []
