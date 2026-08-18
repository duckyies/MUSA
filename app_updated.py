from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Enable CORS for JavaScript client

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'music_db'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'port': os.getenv('DB_PORT', 3306)
}

def get_db_connection():
    """Create and return a database connection"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def execute_query(query, params=None):
    """Execute a query and return results"""
    connection = get_db_connection()
    if not connection:
        return None

    cursor = connection.cursor(dictionary=True)

    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        query_type = query.strip().upper()

        if query_type.startswith(('SELECT', 'SHOW', 'DESCRIBE', 'DESC')):
            results = cursor.fetchall()
            return results
        else:
            connection.commit()
            return {'affected_rows': cursor.rowcount}

    except Error as e:
        print(f"Query error: {e}")
        return None

    finally:
        cursor.close()
        connection.close()

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')

@app.route('/api/test-connection')
def test_connection():
    """Test database connection"""
    connection = get_db_connection()
    if connection:
        connection.close()
        return jsonify({
            'status': 'success',
            'message': 'Database connection successful',
            'timestamp': datetime.now().isoformat()
        })
    else:
        return jsonify({
            'status': 'error',
            'message': 'Database connection failed',
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/api/tables')
def get_tables():
    """Get list of all tables"""
    query = "SHOW TABLES"
    results = execute_query(query)
    if results:
        tables = [list(table.values())[0] for table in results]
        return jsonify({
            'status': 'success',
            'tables': tables
        })
    return jsonify({
        'status': 'error',
        'message': 'Failed to fetch tables'
    }), 500

@app.route('/api/table-schema/<table_name>')
def get_table_schema(table_name):
    """Get column metadata so the frontend can build an insert form."""
    connection = get_db_connection()
    if not connection:
        return jsonify({'status': 'error', 'message': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SHOW TABLES")
        tables = {list(row.values())[0] for row in cursor.fetchall()}

        if table_name not in tables:
            return jsonify({'status': 'error', 'message': f'Unknown table: {table_name}'}), 404

        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        return jsonify({
            'status': 'success',
            'table': table_name,
            'columns': cursor.fetchall()
        })
    except Error as e:
        print(f"Schema query error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@app.route('/api/insert/<table_name>', methods=['POST'])
def insert_record(table_name):
    """Safely insert one record using only columns that exist in the selected table."""
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({'status': 'error', 'message': 'Request body must be a JSON object'}), 400

    connection = get_db_connection()
    if not connection:
        return jsonify({'status': 'error', 'message': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SHOW TABLES")
        tables = {list(row.values())[0] for row in cursor.fetchall()}

        if table_name not in tables:
            return jsonify({'status': 'error', 'message': f'Unknown table: {table_name}'}), 404

        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        schema = cursor.fetchall()
        column_info = {column['Field']: column for column in schema}

        unknown = set(payload) - set(column_info)
        if unknown:
            return jsonify({
                'status': 'error',
                'message': f"Unknown column(s): {', '.join(sorted(unknown))}"
            }), 400

        # Skip blank optional/default fields so MySQL can apply NULL/default values.
        data = {}
        for column, value in payload.items():
            if value == '' and (
                column_info[column]['Null'] == 'YES' or
                column_info[column]['Default'] is not None
            ):
                continue
            data[column] = value

        if not data:
            return jsonify({'status': 'error', 'message': 'Please enter at least one value'}), 400

        columns = list(data.keys())
        column_sql = ', '.join(f'`{column}`' for column in columns)
        placeholders = ', '.join(['%s'] * len(columns))
        query = f"INSERT INTO `{table_name}` ({column_sql}) VALUES ({placeholders})"

        cursor.execute(query, [data[column] for column in columns])
        connection.commit()

        return jsonify({
            'status': 'success',
            'message': f'Record added to {table_name}',
            'inserted_id': cursor.lastrowid if cursor.lastrowid else None,
            'affected_rows': cursor.rowcount
        })
    except Error as e:
        connection.rollback()
        print(f"Insert error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400
    finally:
        cursor.close()
        connection.close()


@app.route('/api/users')
def get_users():
    """Get all users"""
    query = """
        SELECT u.username, u.time_listened, u.is_artist, 
               a.production_house, a.no_listeners, a.country, a.is_band
        FROM users u
        LEFT JOIN artists a ON u.username = a.username
        ORDER BY u.username
    """
    results = execute_query(query)
    if results is not None:
        return jsonify({
            'status': 'success',
            'data': results,
            'count': len(results)
        })
    return jsonify({
        'status': 'error',
        'message': 'Failed to fetch users'
    }), 500

@app.route('/api/songs')
def get_songs():
    """Get all songs with artist information"""
    query = """
        SELECT s.song_id, s.song_name, s.artist_username, 
               s.publish_date, s.listen_count, s.genre, s.duration_seconds,
               a.country, a.is_band
        FROM songs s
        LEFT JOIN artists a ON s.artist_username = a.username
        ORDER BY s.song_id DESC
    """
    results = execute_query(query)
    if results is not None:
        return jsonify({
            'status': 'success',
            'data': results,
            'count': len(results)
        })
    return jsonify({
        'status': 'error',
        'message': 'Failed to fetch songs'
    }), 500

@app.route('/api/artists')
def get_artists():
    """Get all artists with member counts"""
    query = """
        SELECT a.username, a.production_house, a.no_listeners, 
               a.country, a.is_band,
               COUNT(am.member_id) as member_count
        FROM artists a
        LEFT JOIN artist_members am ON a.username = am.artist_username
        GROUP BY a.username
        ORDER BY a.username
    """
    results = execute_query(query)
    if results is not None:
        return jsonify({
            'status': 'success',
            'data': results,
            'count': len(results)
        })
    return jsonify({
        'status': 'error',
        'message': 'Failed to fetch artists'
    }), 500

@app.route('/api/playlists')
def get_playlists():
    """Get all playlists with song counts"""
    query = """
        SELECT p.playlist_id, p.created_by_username, p.last_updated_at,
               p.creation_date, p.cover_art_url,
               COUNT(ps.song_id) as song_count
        FROM playlists p
        LEFT JOIN playlist_songs ps ON p.playlist_id = ps.playlist_id
        GROUP BY p.playlist_id
        ORDER BY p.playlist_id DESC
    """
    results = execute_query(query)
    if results is not None:
        return jsonify({
            'status': 'success',
            'data': results,
            'count': len(results)
        })
    return jsonify({
        'status': 'error',
        'message': 'Failed to fetch playlists'
    }), 500

@app.route('/api/artist-members')
def get_artist_members():
    """Get all artist members"""
    query = """
        SELECT am.member_id, am.artist_username, am.member_name,
               a.country, a.is_band
        FROM artist_members am
        LEFT JOIN artists a ON am.artist_username = a.username
        ORDER BY am.artist_username, am.member_id
    """
    results = execute_query(query)
    if results is not None:
        return jsonify({
            'status': 'success',
            'data': results,
            'count': len(results)
        })
    return jsonify({
        'status': 'error',
        'message': 'Failed to fetch artist members'
    }), 500

@app.route('/api/liked-songs')
def get_liked_songs():
    """Get all liked songs with details"""
    query = """
        SELECT ls.username, ls.song_id, ls.liked_at,
               s.song_name, s.artist_username
        FROM liked_songs ls
        LEFT JOIN songs s ON ls.song_id = s.song_id
        ORDER BY ls.liked_at DESC
        LIMIT 100
    """
    results = execute_query(query)
    if results is not None:
        return jsonify({
            'status': 'success',
            'data': results,
            'count': len(results)
        })
    return jsonify({
        'status': 'error',
        'message': 'Failed to fetch liked songs'
    }), 500

@app.route('/api/listen-history')
def get_listen_history():
    """Get recent listen history"""
    query = """
        SELECT lh.history_id, lh.username, lh.song_id, lh.listened_at,
               s.song_name, s.artist_username
        FROM listen_history lh
        LEFT JOIN songs s ON lh.song_id = s.song_id
        ORDER BY lh.listened_at DESC
        LIMIT 100
    """
    results = execute_query(query)
    if results is not None:
        return jsonify({
            'status': 'success',
            'data': results,
            'count': len(results)
        })
    return jsonify({
        'status': 'error',
        'message': 'Failed to fetch listen history'
    }), 500

@app.route('/api/all-data')
def get_all_data():
    """Get all data from all tables (for quick inspection)"""
    tables = ['users', 'artists', 'songs', 'playlists']
    all_data = {}
    
    for table in tables:
        query = f"SELECT * FROM {table} LIMIT 50"
        results = execute_query(query)
        all_data[table] = results if results else []
    
    return jsonify({
        'status': 'success',
        'data': all_data
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
