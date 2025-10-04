"""
Database connection management for LeadsManager application
"""

import os
import psycopg2
import psycopg2.extras
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Centralized database connection manager for PostgreSQL"""

    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            logger.warning("DATABASE_URL environment variable not set")

    def get_connection(self):
        """Get a database connection"""
        if not self.database_url:
            logger.warning("No DATABASE_URL configured")
            return None

        try:
            # Handle SQLite connections
            if self.is_sqlite or self.database_url.startswith('sqlite:///'):
                from local_config import get_local_connection
                conn = get_local_connection()
                if conn:
                    logger.debug("SQLite database connection established")
                return conn

            # Handle PostgreSQL connections
            # Parse database URL for connection
            url = urlparse(self.database_url)

            # Heroku DATABASE_URL format: postgres://user:password@host:port/database
            # But psycopg2 expects postgresql://
            if url.scheme == 'postgres':
                # Convert postgres:// to postgresql:// for psycopg2
                connection_url = self.database_url.replace('postgres://', 'postgresql://', 1)
            else:
                connection_url = self.database_url

            conn = psycopg2.connect(connection_url)
            conn.autocommit = False  # Use transactions
            logger.debug("PostgreSQL database connection established")
            return conn

        except psycopg2.OperationalError as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected database error: {e}")
            return None

    def test_connection(self):
        """Test database connectivity"""
        try:
            conn = self.get_connection()
            if not conn:
                return False

            cur = conn.cursor()
            cur.execute("SELECT 1")
            result = cur.fetchone()
            cur.close()
            conn.close()

            return result is not None

        except Exception as e:
            logger.error(f"Database test failed: {e}")
            return False

# Global instance
db_manager = DatabaseManager()