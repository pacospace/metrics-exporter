#!/usr/bin/env python3
# thoth-metrics
# Copyright(C) 2018, 2019 Christoph Görn, Francesco Murdaca, Fridolin Pokorny
#
# This program is free software: you can redistribute it and / or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""This is a Prometheus exporter for Thoth."""

import os
import logging
from datetime import datetime
import typing
from functools import partial

from flask_apscheduler import APScheduler
from flask import Flask
from flask import redirect
from flask import make_response
from flask import jsonify
from prometheus_client import generate_latest

from thoth.common import init_logging
from thoth.metrics_exporter import __version__
from thoth.metrics_exporter.jobs import ALL_REGISTERED_JOBS

init_logging()

_LOGGER = logging.getLogger("thoth.metrics_exporter")
_DEBUG = os.getenv("METRICS_EXPORTER_DEBUG", False)
_UPDATE_INTERVAL_SECONDS = int(os.getenv("THOTH_METRICS_EXPORTER_UPDATE_INTERVAL", 20))
_JOBS_RUN = 0
_INITIALIZED = False
_FIRST_RUN_TIME = datetime.now()


def func_wrapper(func: typing.Callable) -> None:
    """A wrapper which counts how many jobs were run."""
    # This simple wrapper wraps the actual function which does metrics
    # gathering to count how many functions were called. If we reach number of
    # all jobs, we know we gathered all metrics and we can expose metrics on
    # /metrics endpoint. Otherwise the application keeps returning HTTP status
    # code 503 signalizing its not ready yet.
    global _JOBS_RUN
    global _INITIALIZED

    func()

    if not _INITIALIZED:
        # Increment/keep track only until we are not initialized.
        _JOBS_RUN += 1


class _Config:
    """Configuration of APScheduler for updating metrics."""

    JOBS = [
        {
            'id': func.__name__,
            'func': partial(func_wrapper, func),
            'trigger': 'interval',
            'seconds': _UPDATE_INTERVAL_SECONDS,
            'next_run_time': _FIRST_RUN_TIME,
            'max_instances': 1,
        }
        for func in ALL_REGISTERED_JOBS
    ]

    SCHEDULER_API_ENABLED = True


application = Flask("thoth.metrics_exporter")
application.config.from_object(_Config())

# Init scheduler.
scheduler = APScheduler()
scheduler.init_app(application)
scheduler.start()


@application.after_request
def extend_response_headers(response):
    """Just add my signature."""
    response.headers["X-Thoth-Metrics-Exporter-Version"] = f"v{__version__}"
    return response


@application.route("/")
def main():
    """Show this to humans."""
    return redirect("https://grafana.datahub.redhat.com", code=308)


@application.route("/metrics")
def metrics():
    """Return the Prometheus Metrics."""
    _LOGGER.debug("Exporting metrics registry...")
    global _INITIALIZED
    global _JOBS_RUN

    if not _INITIALIZED:
        if _JOBS_RUN < len(_Config.JOBS):
            return make_response(jsonify({"error": "Metrics are not ready yet"}), 503)

        # Torn on the switch, we do not need to keep track of not-ready jobs.
        _INITIALIZED = True

    return generate_latest().decode("utf-8")


if __name__ == "__main__":
    _LOGGER.debug("Debug mode is on")
    _LOGGER.info(f"Thoth Metrics Exporter v{__version__} starting...")
    application.run(host="0.0.0.0", port=8080)
