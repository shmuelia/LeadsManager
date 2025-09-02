#!/usr/bin/env python3
"""
Performance Optimization Script for LeadsManager
Adds database indexes and optimizations for faster data fetching
"""

import psycopg2
import psycopg2.extras
import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_connection():
    """Get database connection"""
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

def create_performance_indexes():
    """Create database indexes for better performance"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Cannot connect to database")
            return False
            
        cur = conn.cursor()
        
        indexes_to_create = [
            # Leads table indexes
            ("idx_leads_customer_id", "CREATE INDEX IF NOT EXISTS idx_leads_customer_id ON leads (customer_id)"),
            ("idx_leads_status", "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status)"),
            ("idx_leads_assigned_to", "CREATE INDEX IF NOT EXISTS idx_leads_assigned_to ON leads (assigned_to)"),
            ("idx_leads_created_time", "CREATE INDEX IF NOT EXISTS idx_leads_created_time ON leads (created_time DESC)"),
            ("idx_leads_received_at", "CREATE INDEX IF NOT EXISTS idx_leads_received_at ON leads (received_at DESC)"),
            ("idx_leads_external_id", "CREATE INDEX IF NOT EXISTS idx_leads_external_id ON leads (external_lead_id)"),
            ("idx_leads_email", "CREATE INDEX IF NOT EXISTS idx_leads_email ON leads (email)"),
            ("idx_leads_phone", "CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads (phone)"),
            
            # Composite indexes for common queries
            ("idx_leads_customer_status", "CREATE INDEX IF NOT EXISTS idx_leads_customer_status ON leads (customer_id, status)"),
            ("idx_leads_customer_assigned", "CREATE INDEX IF NOT EXISTS idx_leads_customer_assigned ON leads (customer_id, assigned_to)"),
            ("idx_leads_customer_time", "CREATE INDEX IF NOT EXISTS idx_leads_customer_time ON leads (customer_id, COALESCE(created_time, received_at) DESC)"),
            ("idx_leads_assigned_customer", "CREATE INDEX IF NOT EXISTS idx_leads_assigned_customer ON leads (assigned_to, customer_id)"),
            
            # Users table indexes
            ("idx_users_username", "CREATE INDEX IF NOT EXISTS idx_users_username ON users (username)"),
            ("idx_users_active", "CREATE INDEX IF NOT EXISTS idx_users_active ON users (active)"),
            ("idx_users_customer_id", "CREATE INDEX IF NOT EXISTS idx_users_customer_id ON users (customer_id)"),
            
            # Lead activities indexes
            ("idx_activities_lead_id", "CREATE INDEX IF NOT EXISTS idx_activities_lead_id ON lead_activities (lead_id)"),
            ("idx_activities_date", "CREATE INDEX IF NOT EXISTS idx_activities_date ON lead_activities (activity_date DESC)"),
            ("idx_activities_customer", "CREATE INDEX IF NOT EXISTS idx_activities_customer ON lead_activities (customer_id)"),
            
            # Customers table indexes
            ("idx_customers_active", "CREATE INDEX IF NOT EXISTS idx_customers_active ON customers (active)"),
        ]
        
        successful_indexes = 0
        for index_name, create_sql in indexes_to_create:
            try:
                logger.info(f"Creating index: {index_name}")
                cur.execute(create_sql)
                successful_indexes += 1
            except Exception as e:
                logger.warning(f"Index {index_name} creation failed or already exists: {e}")
        
        # Commit all index creations
        conn.commit()
        
        logger.info(f"Successfully created {successful_indexes}/{len(indexes_to_create)} indexes")
        
        # Update table statistics for better query planning
        logger.info("Updating table statistics...")
        cur.execute("ANALYZE leads")
        cur.execute("ANALYZE users") 
        cur.execute("ANALYZE lead_activities")
        cur.execute("ANALYZE customers")
        
        conn.commit()
        cur.close()
        conn.close()
        
        return True
        
    except Exception as e:
        logger.error(f"Error creating performance indexes: {e}")
        return False

def optimize_database_settings():
    """Apply database-level performance optimizations"""
    try:
        conn = get_db_connection()
        if not conn:
            return False
            
        cur = conn.cursor()
        
        # Get current database stats
        cur.execute("SELECT count(*) FROM leads")
        lead_count = cur.fetchone()[0]
        
        cur.execute("SELECT count(*) FROM users")
        user_count = cur.fetchone()[0]
        
        cur.execute("SELECT count(*) FROM lead_activities")
        activity_count = cur.fetchone()[0]
        
        logger.info(f"Database size: {lead_count} leads, {user_count} users, {activity_count} activities")
        
        # Set work_mem for better sorting performance (session-level)
        cur.execute("SET work_mem = '16MB'")
        
        # Enable parallel query execution
        cur.execute("SET max_parallel_workers_per_gather = 2")
        
        cur.close()
        conn.close()
        
        return True
        
    except Exception as e:
        logger.error(f"Error optimizing database settings: {e}")
        return False

def check_query_performance():
    """Check performance of main queries"""
    try:
        conn = get_db_connection()
        if not conn:
            return False
            
        cur = conn.cursor()
        
        # Test main leads query performance
        start_time = datetime.now()
        
        cur.execute("""
            SELECT l.id, l.name, l.status, l.assigned_to, l.created_time, l.received_at, 
                   u.full_name as assigned_full_name
            FROM leads l
            LEFT JOIN users u ON l.assigned_to = u.username AND u.active = true
            WHERE l.customer_id = 1 OR l.customer_id IS NULL
            ORDER BY COALESCE(l.created_time, l.received_at) DESC
            LIMIT 100
        """)
        
        leads = cur.fetchall()
        end_time = datetime.now()
        
        query_time = (end_time - start_time).total_seconds()
        logger.info(f"Main leads query took {query_time:.3f} seconds for {len(leads)} results")
        
        cur.close()
        conn.close()
        
        return query_time < 1.0  # Should be under 1 second
        
    except Exception as e:
        logger.error(f"Error checking query performance: {e}")
        return False

if __name__ == "__main__":
    logger.info("Starting LeadsManager performance optimization...")
    
    # Create performance indexes
    if create_performance_indexes():
        logger.info("✅ Database indexes created successfully")
    else:
        logger.error("❌ Failed to create database indexes")
    
    # Optimize database settings  
    if optimize_database_settings():
        logger.info("✅ Database settings optimized")
    else:
        logger.error("❌ Failed to optimize database settings")
    
    # Check query performance
    if check_query_performance():
        logger.info("✅ Query performance is good")
    else:
        logger.warning("⚠️ Query performance needs improvement")
    
    logger.info("Performance optimization completed!")