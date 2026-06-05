import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase

from qatrack.qatrack_core.management.commands.backup_site import Command


class BackupSiteTest(TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cmd = Command()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_check_permissions_success(self):
        """Test that check_permissions succeeds when the directory is writable."""
        backup_loc = os.path.join(self.temp_dir, 'writable_dir')
        result = self.cmd.check_permissions(backup_loc)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(backup_loc))

    @patch('builtins.open', side_effect=PermissionError("Permission denied"))
    def test_check_permissions_failure(self, mock_open):
        """Test that check_permissions fails gracefully on a PermissionError."""
        backup_loc = os.path.join(self.temp_dir, 'unwritable_dir')
        # We also need to mock os.makedirs to prevent failure there if it already exists
        with patch('os.makedirs'):
            result = self.cmd.check_permissions(backup_loc)
        self.assertFalse(result)

    @patch('qatrack.qatrack_core.management.commands.backup_site.Command.run_backup')
    @patch('qatrack.qatrack_core.management.commands.backup_site.Command.get_setting')
    def test_test_flag(self, mock_get_setting, mock_run_backup):
        """Test that the --test flag only tests permissions and doesn't create backups."""
        mock_get_setting.return_value = self.temp_dir
        
        call_command('backup_site', '--test')
        
        # Ensure run_backup was called exactly once with test_only=True
        mock_run_backup.assert_called_once()
        args, kwargs = mock_run_backup.call_args
        self.assertTrue(kwargs.get('test_only'))

    @patch('subprocess.run')
    @patch('qatrack.qatrack_core.management.commands.backup_site.settings')
    def test_postgresql_backup(self, mock_settings, mock_subprocess):
        """Test that pg_dump is called correctly for PostgreSQL."""
        mock_settings.DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': 'qatrackdb',
                'HOST': 'localhost',
                'USER': 'qatrack',
                'PASSWORD': 'password',
            }
        }
        mock_settings.MEDIA_ROOT = self.temp_dir
        
        # Test dry-run of postgres backup execution
        result = self.cmd.run_backup(self.temp_dir, 'daily', 'qatrackdb', test_only=False)
        
        # Since subprocess is mocked, it shouldn't fail
        # Wait, the zip creation will try to zip MEDIA_ROOT
        self.assertTrue(result)
        mock_subprocess.assert_called_once()
        cmd_args = mock_subprocess.call_args[0][0]
        self.assertIn('pg_dump', cmd_args)
        self.assertIn('qatrackdb', cmd_args)
        self.assertIn('-U', cmd_args)

    @patch('subprocess.run')
    @patch('qatrack.qatrack_core.management.commands.backup_site.settings')
    def test_mysql_backup(self, mock_settings, mock_subprocess):
        """Test that mysqldump is called correctly for MySQL."""
        mock_settings.DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.mysql',
                'NAME': 'qatrackdb',
                'HOST': 'localhost',
                'USER': 'qatrack',
            }
        }
        mock_settings.MEDIA_ROOT = self.temp_dir
        
        result = self.cmd.run_backup(self.temp_dir, 'daily', 'qatrackdb', test_only=False)
        
        self.assertTrue(result)
        mock_subprocess.assert_called_once()
        cmd_args = mock_subprocess.call_args[0][0]
        self.assertIn('mysqldump', cmd_args)
        self.assertIn('qatrackdb', cmd_args)

    @patch('qatrack.qatrack_core.management.commands.backup_site.connection')
    @patch('qatrack.qatrack_core.management.commands.backup_site.settings')
    def test_mssql_backup(self, mock_settings, mock_connection):
        """Test that BACKUP DATABASE is called correctly for SQL Server."""
        mock_settings.DATABASES = {
            'default': {
                'ENGINE': 'sql_server.pyodbc',
                'NAME': 'qatrackdb',
            }
        }
        mock_settings.MEDIA_ROOT = self.temp_dir
        
        # Mock connection cursor
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        
        result = self.cmd.run_backup(self.temp_dir, 'daily', 'qatrackdb', test_only=False)
        
        self.assertTrue(result)
        mock_connection.ensure_connection.assert_called_once()
        mock_cursor.execute.assert_called_once()
        query = mock_cursor.execute.call_args[0][0]
        self.assertIn("BACKUP DATABASE [qatrackdb] TO DISK=", query)

    @patch('shutil.copy2')
    @patch('qatrack.qatrack_core.management.commands.backup_site.settings')
    def test_sqlite_backup(self, mock_settings, mock_copy2):
        """Test that shutil.copy2 is called correctly for SQLite."""
        mock_settings.DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': os.path.join(self.temp_dir, 'db.sqlite3'),
            }
        }
        mock_settings.MEDIA_ROOT = self.temp_dir
        
        result = self.cmd.run_backup(self.temp_dir, 'daily', 'qatrackdb', test_only=False)
        
        self.assertTrue(result)
        mock_copy2.assert_called_once()
        args = mock_copy2.call_args[0]
        self.assertEqual(args[0], mock_settings.DATABASES['default']['NAME'])
        self.assertTrue(args[1].endswith('qatrackdb-script.bak'))
