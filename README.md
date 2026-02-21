# FieldCam

A FastAPI-based web application for scheduling and managing live camera streams for ball field events. FieldCam allows users to schedule streaming sessions, automatically capturing and serving field camera images for scheduled games and practices.

## Features

- 🎥 **Live Field Camera Integration** - Capture and serve real-time field images
- 📅 **Job Scheduling** - Schedule streaming sessions with start/end times
- 🔐 **User Authentication** - Secure login system with session management
- 🎬 **Automated Streaming** - Automatically start/stop streams based on schedule
- 🐳 **Docker Support** - Fully containerized deployment
- 📊 **Job Management** - Web interface for adding, listing, and removing scheduled jobs
- 🔄 **Auto-restart** - Automatic container restart on failure

## Prerequisites

- Docker and Docker Compose
- RTSP camera feed (IP camera with RTSP support)
- FFmpeg (for image capture via cron)

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/jkrauska/fieldcam.git
cd fieldcam
```

### 2. Configure Environment Variables

Copy the example environment file and configure your settings:

```bash
cp cam-app/.env.example cam-app/.env
```

Edit `cam-app/.env` with your configuration:

```bash
# Security Settings (REQUIRED)
SECRET_KEY=your-secret-key-here
COOKIE_NAME=stream411_login

# Camera Configuration (REQUIRED)
CAM_HOST=192.168.x.x
CAM_USER=admin
CAM_PASS=your-camera-password

# Application Settings
LOCATION=Tepper
LONG_STRING=your-long-string-here

# Authentication
AUTH_HASH_SFLL=$2b$12$your-bcrypt-hash-here
PASSWORDS=password1,password2,password3

# Optional Settings
TIMEZONE=America/Los_Angeles
TOKEN_EXPIRY_MINUTES=30
JOBS_DB_PATH=sqlite:///jobs/jobs.sqlite
```

**Migration from secrets.json**: If you have an existing `secrets.json` file, you can use the migration script:

```bash
cd cam-app
python migrate_to_env.py
```

### 3. Build and Start

```bash
# Build the Docker image
./build.sh

# Start the application
./d-up.sh
```

The application will be available at `http://localhost:9090`

### 4. Set Up Image Capture (Cron)

Add a cron job to capture field snapshots:

```bash
crontab -e
```

Add this line (adjust credentials and IP address):

```cron
* * * * * /usr/bin/ffmpeg -hide_banner -loglevel error -y -i rtsp://USERNAME:PASSWORD@IPADDRESS:554/Streaming/channels/102/ -frames:v 1 -q:v 2 /home/stream411/fieldcam/cam-app/app/static/field.jpg
```

## Project Structure

```
fieldcam/
├── cam-app/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI application entry point
│   │   ├── auth.py          # Authentication logic
│   │   ├── routes.py        # Application routes
│   │   ├── config.py        # Configuration management
│   │   ├── scheduler.py     # Job scheduling logic
│   │   ├── streaming.py     # Streaming management
│   │   ├── random_names.py  # Stream key generation
│   │   ├── static/          # Static files (images, favicon)
│   │   └── templates/       # Jinja2 templates
│   ├── Dockerfile           # Container definition
│   ├── requirements.txt     # Python dependencies
│   └── build.sh            # Docker build script
├── jobs/                    # SQLite database storage
├── logs/                    # Application logs
├── docker-compose.yml       # Docker Compose configuration
├── d-up.sh                 # Start container script
├── d-down.sh               # Stop container script
├── logs.sh                 # View logs script
└── README.md               # This file
```

## API Endpoints

### Public Endpoints
- `GET /login` - Login form
- `POST /login` - Handle login submission

### Authenticated Endpoints
- `GET /dynamic/field.jpg` - Serve current field image (no cache)
- `GET /list` - List all scheduled jobs
- `GET /add` - Add new streaming job form
- `POST /submit` - Submit new streaming job
- `POST /remove_job` - Remove a scheduled job
- `GET /logout` - Log out current user
- `GET /version` - Application version information

## Usage

### Adding a Streaming Job

1. Navigate to `http://localhost:9090/list`
2. Log in with your credentials
3. Click "Add Job" or go to `/add`
4. Fill in the form:
   - **Team Name**: Name of the team or event
   - **Date**: Date of the game (YYYY-MM-DD)
   - **Start Time**: Stream start time (HH:MM)
   - **End Time**: Stream end time (HH:MM)
   - **Stream Key**: (Optional) Custom stream key or auto-generated
5. Click Submit

### Managing Jobs

- View all scheduled jobs at `/list`
- Remove jobs by clicking the remove button next to each job
- Jobs are automatically executed based on their scheduled time

### Viewing the Field Camera

Access the live field image at `/dynamic/field.jpg` (requires authentication)

## Development

### Local Development Setup

#### Prerequisites

Install [uv](https://github.com/astral-sh/uv) - a fast Python package installer:

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Reload your shell or add to PATH
source $HOME/.local/bin/env
```

#### Setting Up the Development Environment

```bash
# Navigate to the cam-app directory
cd cam-app

# Create a virtual environment with uv
uv venv

# Activate the virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install production dependencies
uv pip install -r requirements.txt

# Install development dependencies (includes ruff and pre-commit)
uv pip install -r requirements-dev.txt

# Install pre-commit hooks (for automatic linting/formatting)
pre-commit install
```

#### Running the Application Locally

```bash
# Make sure you're in the cam-app directory with venv activated
cd cam-app
uvicorn app.main:app --reload --port 9090
```

### Code Quality Tools

This project uses [Ruff](https://github.com/astral-sh/ruff) for linting and formatting.

#### Automatic Formatting (Pre-commit Hooks)

Once you've run `pre-commit install`, ruff will automatically:
- Check for linting issues and auto-fix them
- Format your code

This happens automatically on every commit.

#### Manual Usage

```bash
# Check for linting issues
ruff check .

# Auto-fix linting issues
ruff check --fix .

# Format all Python files
ruff format .

# Check a specific file
ruff check cam-app/app/main.py
```

#### Configuration

Ruff configuration is in `pyproject.toml`:
- Line length: 100 characters
- Python version: 3.11
- Enabled rules: pyflakes, pycodestyle, isort, pep8-naming, pyupgrade, flake8-bugbear, and more

#### Continuous Integration

GitHub Actions automatically runs ruff checks on all pull requests and pushes to main/master branches. The workflow:
- Checks for linting issues with `ruff check`
- Verifies code formatting with `ruff format --check`

See `.github/workflows/lint.yml` for the workflow configuration.

### Technology Stack

- **FastAPI** - Modern Python web framework
- **Uvicorn** - ASGI server
- **APScheduler** - Job scheduling
- **SQLAlchemy** - Database ORM
- **Jinja2** - Template engine
- **FastAPI-Login** - Authentication
- **Data-Star** - Lightweight hypermedia frontend (CDN script, no npm); backend-driven UI with HTML patch responses
- **Docker** - Containerization

### Data-Star integration

The list and add pages use [Data-Star](https://data-star.dev/) so that actions (remove job, cancel stream, submit new stream) update the page via **HTML morphing** instead of full reloads:

- **List page** (`/list`): Remove and Cancel buttons submit via `@post(..., {contentType: 'form'})`. The server returns an HTML fragment for `#list-content`, which Data-Star morphs into the DOM.
- **Add page** (`/add`): The form uses `data-on:submit="@post('/submit', {contentType: 'form'})"`. On success the server returns a fragment for `#add-form-container` (success message + link back to list).

No frontend build step or Data-Star SDK is required; the client loads the Data-Star script from the CDN, and the backend returns plain HTML fragments with the expected element IDs.

### Building the Docker Image

```bash
./cam-app/build.sh
```

Or manually:

```bash
cd cam-app
docker build -t camapp:latest .
```

## Scripts

- **build.sh** - Build the Docker image
- **d-up.sh** - Start the Docker container
- **d-down.sh** - Stop the Docker container
- **logs.sh** - View container logs

## Configuration

### Environment Variables

The application uses Pydantic Settings for configuration management. All configuration is loaded from environment variables (via `.env` file):

**Required Variables:**
- `SECRET_KEY` - Secret key for session management
- `CAM_HOST` - Camera IP address
- `CAM_USER` - Camera username
- `CAM_PASS` - Camera password
- `AUTH_HASH_SFLL` - BCrypt hash for authentication
- `PASSWORDS` - Comma-separated list of valid passwords

**Optional Variables:**
- `COOKIE_NAME` - Cookie name for sessions (default: `stream411_login`)
- `LOCATION` - Location name (default: `Tepper`)
- `TIMEZONE` - Timezone for scheduling (default: `America/Los_Angeles`)
- `TOKEN_EXPIRY_MINUTES` - Session token expiry (default: `30`)
- `JOBS_DB_PATH` - SQLite database path (default: `sqlite:///jobs/jobs.sqlite`)

### Docker Configuration

- Port: `9090` (mapped in docker-compose.yml)
- Environment file: `cam-app/.env` (loaded via docker-compose.yml)

### Docker Volumes

- `./cam-app/app/static` → `/code/app/static` - Field images
- `./jobs` → `/code/jobs` - SQLite database
- `./logs` → `/code/logs` - Application logs

## Troubleshooting

### Container Issues

```bash
# View logs
./logs.sh
# or
docker logs camapp

# Restart container
./d-down.sh && ./d-up.sh

# Rebuild and restart
./cam-app/build.sh && ./d-down.sh && ./d-up.sh
```

### Image Not Updating

Check if the cron job is running:
```bash
crontab -l
```

Verify FFmpeg can access your camera:
```bash
ffmpeg -i rtsp://USERNAME:PASSWORD@IPADDRESS:554/Streaming/channels/102/ -frames:v 1 test.jpg
```

### Login Issues

Verify your `.env` file exists and contains valid credentials:

```bash
# Check if .env file exists
ls -la cam-app/.env

# Verify required variables are set
grep -E "SECRET_KEY|CAM_HOST|AUTH_HASH_SFLL" cam-app/.env
```

### Configuration Issues

If you encounter configuration errors:

1. Ensure all required environment variables are set in `cam-app/.env`
2. Check that the `.env` file is being loaded by docker-compose
3. Verify the format of environment variables (no quotes needed for most values)
4. For comma-separated values like `PASSWORDS`, ensure no spaces after commas

## Future Improvements

- [ ] Move image capture to Docker container (eliminate cron dependency)
- [ ] Add support for multiple camera feeds
- [ ] Implement RTMP/HLS streaming output
- [ ] Add email notifications for scheduled jobs
- [ ] Create admin dashboard with analytics
- [ ] Add API key authentication for programmatic access

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

See [LICENSE](LICENSE) file for details.

## Support

For issues, questions, or contributions, please visit the [GitHub repository](https://github.com/jkrauska/fieldcam).
