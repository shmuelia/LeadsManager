#!/usr/bin/env python3
"""
Environment setup script for LeadsManager
This script helps you set up the environment variables needed to run the application locally
"""

import os
import subprocess
import sys

def check_postgresql_installed():
    """Check if PostgreSQL is installed and running"""
    try:
        result = subprocess.run(['psql', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ PostgreSQL found: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("❌ PostgreSQL not found. Please install PostgreSQL first.")
    print("   Download from: https://www.postgresql.org/download/")
    return False

def create_local_database():
    """Create a local PostgreSQL database for development"""
    db_name = "leadsmanager_dev"
    db_user = "postgres"
    db_password = input("Enter PostgreSQL password for 'postgres' user: ")
    
    try:
        # Create database
        env = os.environ.copy()
        env['PGPASSWORD'] = db_password
        
        # Check if database exists
        result = subprocess.run([
            'psql', '-U', db_user, '-h', 'localhost', '-c', 
            f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"
        ], env=env, capture_output=True, text=True)
        
        if db_name in result.stdout:
            print(f"✅ Database '{db_name}' already exists")
        else:
            # Create database
            result = subprocess.run([
                'createdb', '-U', db_user, '-h', 'localhost', db_name
            ], env=env, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ Database '{db_name}' created successfully")
            else:
                print(f"❌ Error creating database: {result.stderr}")
                return None
        
        # Return database URL
        return f"postgresql://{db_user}:{db_password}@localhost:5432/{db_name}"
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def setup_environment():
    """Set up environment variables"""
    print("🚀 Setting up LeadsManager environment...")
    
    # Check PostgreSQL
    if not check_postgresql_installed():
        return False
    
    # Create database
    database_url = create_local_database()
    if not database_url:
        return False
    
    # Create .env file
    env_content = f"""# LeadsManager Environment Variables
DATABASE_URL={database_url}
SECRET_KEY=your-local-secret-key-change-this
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
FROM_EMAIL=your-email@gmail.com
"""
    
    try:
        with open('.env', 'w') as f:
            f.write(env_content)
        print("✅ Created .env file with database configuration")
    except Exception as e:
        print(f"❌ Error creating .env file: {e}")
        return False
    
    print("\n🎉 Environment setup complete!")
    print("\nNext steps:")
    print("1. Run: python setup_database.py")
    print("2. Run: python app.py")
    print("3. Open: http://localhost:5000")
    print("4. Login with: admin / admin123")
    
    return True

if __name__ == "__main__":
    setup_environment()
