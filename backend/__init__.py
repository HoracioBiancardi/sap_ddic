"""Backend package for the SAP Metadata Discovery Web App.

Contains the FastAPI application and all supporting modules responsible for
connecting to the SAP Datasphere (HANA) replica, classifying DDIC metadata
through business heuristics, caching results, and serving the JSON contract
consumed by the vanilla JS frontend.
"""
