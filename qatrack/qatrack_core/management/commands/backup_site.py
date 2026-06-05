import datetime
import glob
import os
import shutil
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Backup QATrack+ database and media uploads'

    def add_arguments(self, parser):
        parser.add_argument(
            '--test',
            action='store_true',
            help='Run a permissions test to verify write access to the backup directory without creating a backup',
        )

    def get_setting(self, name, default):
        return getattr(settings, name, default)

    def remove_old(self, backup_dir, backup_type, limit_date):
        pattern = os.path.join(backup_dir, f"*-{backup_type}")
        for path in glob.glob(pattern):
            if os.path.isdir(path):
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).date()
                if mtime < limit_date:
                    self.stdout.write(f"Removing old {backup_type} backup: {path}")
                    shutil.rmtree(path)

    def check_permissions(self, backup_loc, test_only=False):
        """Test if we can write to the backup directory."""
        if test_only:
            self.stdout.write("\nRunning backup pre-flight checks...")
            self.stdout.write(f"  [*] Checking backup directory: {backup_loc}")
            
        if not os.path.exists(backup_loc):
            try:
                os.makedirs(backup_loc)
                if test_only:
                    self.stdout.write(self.style.SUCCESS(f"  [OK] Created directory {backup_loc}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  [FAIL] Cannot create directory {backup_loc}: {e}"))
                return False
        else:
            if test_only:
                self.stdout.write(self.style.SUCCESS(f"  [OK] Directory {backup_loc} exists"))
                
        test_file = os.path.join(backup_loc, '.write_test')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            if test_only:
                self.stdout.write(self.style.SUCCESS(f"  [OK] App write access verified for {backup_loc}"))
            return True
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  [FAIL] App permission denied. Cannot write to {backup_loc}: {e}"))
            return False

    def run_backup(self, backup_dir, backup_type, db_name, test_only=False):
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        backup_loc = os.path.join(backup_dir, f"{today_str}-{backup_type}")
        
        if not self.check_permissions(backup_loc, test_only=test_only):
            return False
            
        if test_only:
            # Media dir test
            media_dir = settings.MEDIA_ROOT
            if media_dir and os.path.exists(media_dir):
                self.stdout.write(self.style.SUCCESS(f"  [OK] Media directory exists: {media_dir}"))
            else:
                self.stdout.write(self.style.WARNING(f"  [WARN] Media directory {media_dir} does not exist or is not set."))

            # Test database write access or client existence
            db_settings = settings.DATABASES['default']
            engine = db_settings['ENGINE']
            
            db_type = 'Unknown'
            if 'mssql' in engine or 'sqlserver' in engine:
                db_type = 'SQL Server'
            elif 'postgresql' in engine:
                db_type = 'PostgreSQL'
            elif 'mysql' in engine:
                db_type = 'MySQL'
            elif 'sqlite3' in engine:
                db_type = 'SQLite'
            self.stdout.write(f"  [*] Detected database type: {db_type} ({engine})")

            if 'mssql' in engine or 'sqlserver' in engine:
                db_dir_override = self.get_setting('BACKUP_DB_DIR', None)
                if db_dir_override:
                    test_sql_loc = f"{db_dir_override}/{today_str}-test"
                    test_sql_file = f"{test_sql_loc}/test_db_access.bak"
                else:
                    test_sql_loc = backup_loc
                    test_sql_file = os.path.join(test_sql_loc, "test_db_access.bak")
                query = f"BACKUP DATABASE [{db_name}] TO DISK='{test_sql_file}' WITH COPY_ONLY"
                self.stdout.write(f"  [*] Testing SQL Server write access to {test_sql_file}...")
                connection.ensure_connection()
                old_autocommit = connection.get_autocommit()
                connection.set_autocommit(True)
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(query)
                    self.stdout.write(self.style.SUCCESS(f"  [OK] Database write access verified for {test_sql_file}"))
                    try:
                        os.remove(test_sql_file)
                    except Exception:
                        pass
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  [FAIL] Database write access test failed: {e}"))
                finally:
                    connection.set_autocommit(old_autocommit)
            elif 'postgresql' in engine:
                if shutil.which('pg_dump'):
                    self.stdout.write(self.style.SUCCESS("  [OK] Found pg_dump executable for PostgreSQL"))
                else:
                    self.stdout.write(self.style.ERROR("  [FAIL] pg_dump executable not found in PATH"))
            elif 'mysql' in engine:
                if shutil.which('mysqldump'):
                    self.stdout.write(self.style.SUCCESS("  [OK] Found mysqldump executable for MySQL"))
                else:
                    self.stdout.write(self.style.ERROR("  [FAIL] mysqldump executable not found in PATH"))
            elif 'sqlite3' in engine:
                 db_path = db_settings['NAME']
                 if os.path.exists(db_path):
                     self.stdout.write(self.style.SUCCESS(f"  [OK] SQLite database file exists: {db_path}"))
                 else:
                     self.stdout.write(self.style.ERROR(f"  [FAIL] SQLite database file not found: {db_path}"))

            self.stdout.write(self.style.SUCCESS("\nTest mode completed successfully. No backups were created."))
            return True

        # 1. Database Backup
        db_settings = settings.DATABASES['default']
        engine = db_settings['ENGINE']
        
        db_dir_override = self.get_setting('BACKUP_DB_DIR', None)
        
        if db_dir_override:
            # Construct the path using forward slashes for Linux/Docker environments
            sql_backup_loc = f"{db_dir_override}/{today_str}-{backup_type}"
            if not os.path.exists(sql_backup_loc) and not db_dir_override.startswith('/'):
                 # only try to create if it's not a remote docker path
                 try:
                     os.makedirs(sql_backup_loc) 
                 except Exception:
                     pass
            sql_backup_file = f"{sql_backup_loc}/{db_name}-script.bak"
        else:
            sql_backup_file = os.path.join(backup_loc, f"{db_name}-script.bak")

        local_backup_file = os.path.join(backup_loc, f"{db_name}-script.bak")
        
        if os.path.exists(local_backup_file):
            os.remove(local_backup_file)
            
        if 'mssql' in engine or 'sqlserver' in engine:
            query = f"BACKUP DATABASE [{db_name}] TO DISK='{sql_backup_file}'"
            connection.ensure_connection()
            old_autocommit = connection.get_autocommit()
            connection.set_autocommit(True)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(query)
                self.stdout.write(self.style.SUCCESS(f"Successfully backed up SQL Server database to {sql_backup_file}"))
            except Exception as e:
                err_msg = str(e)
                self.stdout.write(self.style.ERROR(f"Failed to backup database: {err_msg}"))
                self.stdout.write(self.style.WARNING(
                    "\n[TIP] Docker or Remote DB Detected?\n"
                    "If SQL Server is running in Docker or on a remote server, it has a completely isolated filesystem "
                    "and cannot write to your local Windows drive directly.\n"
                    "To fix this:\n"
                    "1. Map your backup folder as a network share or Docker volume (e.g. `-v C:\\deploy\\backups:/backups`)\n"
                    "2. Add `BACKUP_DB_DIR = '/backups'` to your `local_settings.py` so the script uses the correct path format."
                ))
                return False
            finally:
                connection.set_autocommit(old_autocommit)
        elif 'postgresql' in engine:
            host = db_settings.get('HOST', 'localhost')
            port = str(db_settings.get('PORT', '5432'))
            user = db_settings.get('USER', 'qatrack')
            password = db_settings.get('PASSWORD', '')
            
            pg_backup_file = os.path.join(backup_loc, f"{db_name}.dump")
            env = os.environ.copy()
            if password:
                env['PGPASSWORD'] = password
            
            cmd = ['pg_dump', '-Fc', '-h', host, '-p', port, '-U', user, db_name, '-f', pg_backup_file]
            try:
                subprocess.run(cmd, env=env, check=True, capture_output=True)
                self.stdout.write(self.style.SUCCESS(f"Successfully backed up PostgreSQL database to {pg_backup_file}"))
            except subprocess.CalledProcessError as e:
                self.stdout.write(self.style.ERROR(f"pg_dump failed: {e.stderr.decode('utf-8', errors='ignore')}"))
                return False
            except FileNotFoundError:
                self.stdout.write(self.style.ERROR("pg_dump executable not found. Please ensure PostgreSQL client tools are installed."))
                return False
                
        elif 'mysql' in engine:
            host = db_settings.get('HOST', 'localhost')
            port = str(db_settings.get('PORT', '3306'))
            user = db_settings.get('USER', 'root')
            password = db_settings.get('PASSWORD', '')
            
            mysql_backup_file = os.path.join(backup_loc, f"{db_name}.sql")
            cmd = ['mysqldump', '-h', host, '-P', port, '-u', user]
            if password:
                cmd.append(f'-p{password}')
            cmd.append(db_name)
            
            try:
                with open(mysql_backup_file, 'wb') as f:
                    subprocess.run(cmd, check=True, stdout=f, stderr=subprocess.PIPE)
                self.stdout.write(self.style.SUCCESS(f"Successfully backed up MySQL database to {mysql_backup_file}"))
            except subprocess.CalledProcessError as e:
                self.stdout.write(self.style.ERROR(f"mysqldump failed: {e.stderr.decode('utf-8', errors='ignore')}"))
                return False
            except FileNotFoundError:
                self.stdout.write(self.style.ERROR("mysqldump executable not found. Please ensure MySQL client tools are installed."))
                return False
                
        elif 'sqlite3' in engine:
            db_path = db_settings['NAME']
            shutil.copy2(db_path, local_backup_file)
            self.stdout.write(self.style.SUCCESS(f"Copied SQLite database to {local_backup_file}"))

        # 2. Media Zip
        media_dir = settings.MEDIA_ROOT
        zip_file_path = os.path.join(backup_loc, 'media.zip')
        if os.path.exists(zip_file_path):
            os.remove(zip_file_path)
            
        if media_dir and os.path.exists(media_dir):
            shutil.make_archive(zip_file_path.replace('.zip', ''), 'zip', media_dir)
            self.stdout.write(self.style.SUCCESS(f"Successfully backed up media to {zip_file_path}"))
        else:
            self.stdout.write(self.style.WARNING(f"Media directory {media_dir} does not exist or is not set. Skipping media backup."))

        return True

    def handle(self, *args, **options):
        backup_dir = self.get_setting('BACKUP_DIR', 'C:\\deploy\\backups')
        weekly_day = self.get_setting('BACKUP_WEEKLY_DAY', 2) # 2 = Wednesday in Python (0=Mon)
        monthly_day = self.get_setting('BACKUP_MONTHLY_DAY', 3)
        
        days_to_keep = self.get_setting('BACKUP_DAYS_TO_KEEP', 7)
        weeks_to_keep = self.get_setting('BACKUP_WEEKS_TO_KEEP', 5)
        months_to_keep = self.get_setting('BACKUP_MONTHS_TO_KEEP', 12)
        
        db_name = settings.DATABASES['default'].get('NAME', 'qatrackplus')
        
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        today = datetime.date.today()
        test_only = options.get('test', False)

        if test_only:
            self.stdout.write("Running in test mode. No backups will be created.")
            self.run_backup(backup_dir, 'test', db_name, test_only=True)
            return

        # Monthly Backup
        if today.day == monthly_day:
            limit_date = today - datetime.timedelta(days=30 * months_to_keep)
            if self.run_backup(backup_dir, 'monthly', db_name):
                self.remove_old(backup_dir, 'monthly', limit_date)

        # Weekly Backup
        if today.weekday() == weekly_day:
            limit_date = today - datetime.timedelta(days=7 * weeks_to_keep)
            if self.run_backup(backup_dir, 'weekly', db_name):
                self.remove_old(backup_dir, 'weekly', limit_date)

        # Daily Backup
        limit_date = today - datetime.timedelta(days=days_to_keep)
        if self.run_backup(backup_dir, 'daily', db_name):
            self.remove_old(backup_dir, 'daily', limit_date)

        self.stdout.write(self.style.SUCCESS("Backup process completed."))
