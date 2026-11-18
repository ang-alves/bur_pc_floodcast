"""Compose data steps into the existing Stage 2 R; do not invent a physical T0.

Use the returned definition with the operational WorkflowRequest supplied by the
caller. This module neither downloads nor executes a model when imported.
"""
from floodcast.core.workflow_contracts import StepSpec, WorkflowDefinition
from floodcast.data.registration import register_data_handlers
from floodcast.data.workflow import register_forecast_steps


def compose_forecast_data(app, data_config):
    register_data_handlers(app.R)
    register_forecast_steps(app.R)
    data = data_config.model_dump(mode="json")
    return WorkflowDefinition(
        workflow_id="ecmwf-data",
        version="1",
        steps=(
            StepSpec(
                step_id="acquire",
                component_id="forecast.acquire",
                configuration={"data": data},
                # A remote store job can survive a client interruption.
                retry_safe=False,
            ),
            StepSpec(
                step_id="normalize",
                component_id="forecast.normalize",
                needs=("acquire",),
                configuration={"data": data, "acquisition_step": "acquire"},
                retry_safe=True,
            ),
        ),
    )
