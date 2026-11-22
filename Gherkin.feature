Feature: Indicator provenance and unit consistency
  As a data-analyst
  I want every indicator value to carry its unit, sensor, date and processing version
  So that I can trust the numbers and avoid unit‑mix‑ups

  Scenario ID: TEST-01
    Given a Sentinel‑2 water‑extent indicator result exists for study area "Lake Malawi"
      with value 12.5 and unit "km²"
    And the processing version is "1.0.0"
    And the sensor is "S2_MPC"
    When I query the API GET /api/v1/indicators/results/{id}
    Then the response JSON must contain "unit": "km²"
    And the response must contain "sensor": "S2_MPC"
    And the response must contain "date": "<ISO‑date>"
    And the response must contain "version": "1.0.0"

Feature: Cloud‑mask flagging
  As a disaster planner
  I need to know when a scene was cloudy and whether gaps were interpolated
  So that I can avoid using unreliable water‑level estimates

  Scenario ID: TEST-02
    Given a MODIS LST ingestion job completed with cloud fraction 60%
    When the quality flag evaluation runs
    Then the result row must have quality_flag = "CLOUD_CONTAMINATED"
    And the result must contain a "cloud_gap_interpolated" boolean = false

Feature: Threshold‑based flood alert
  As an operations manager
  I want the system to raise a flood alert when water‑level exceeds the approved threshold
  So that warning actions can be taken

  Scenario ID: TEST-03
    Given an approved threshold for "water_level_altitude" with value_low = 475.0 m
    And the latest forecast value for study area "North Basin" is 482.3 m
    When the disaster evaluate job runs
    Then an alert of hazard type "flood" must be created
    And the alert severity must be "warning"

Feature: Public dashboard filters
  As an anonymous website visitor
  I only want to see datasets that are marked public
  So that I do not accidentally view internal data

  Scenario ID: TEST-04
    Given two datasets exist: one with is_public=true, one with is_public=false
    When I call GET /public/datasets
    Then the response list must contain only the public dataset

Feature: Unit‑mismatch detection in tests
  As a developer
  I want unit tests to catch metre/centimetre and coordinate‑system mix‑ups
  So that erroneous data never reach production

  Scenario ID: TEST-05
    Given a Python test that creates an IndicatorResult with value 1500 and unit "cm"
    When the test runs the unit‑consistency validator
    Then the test must fail with error “Unit mismatch: expected m, got cm”

Feature: Audit log captures threshold changes
  As a compliance officer
  I need a permanent record of every threshold modification
  So that we can demonstrate governance during an audit

  Scenario ID: TEST-06
    Given a super‑admin patches threshold "water_extent" operator from "gte" to "gt"
    When the patch request succeeds
    Then a new row appears in audit_log with action="threshold.update"
    And the row includes old_operator="gte", new_operator="gt", timestamp

Feature: Report snapshot freeze
  As a researcher
  I want the PDF report to contain frozen statistics that never change after build
  So that downstream consumers have a reproducible snapshot

  Scenario ID: TEST-07
    Given a periodic report build for period "monthly" with indicator results containing NULLs
    When the build completes
    Then summary_json must contain a "null_count" field equal to the number of NULL results at build time
    And subsequent addition of new results must not alter the previously downloaded PDF

Feature: Role‑based UI visibility
  As a researcher
  I should not see the “Publish to public” button
  So that I cannot unintentionally make data public

  Scenario ID: TEST-08
    Given a user with role "researcher" logs into the frontend
    When the page `PublicDashboardPage` renders
    Then the “Publish” button must be absent from the DOM

Feature: Daily scheduler triggers indicator recompute
  As an operator
  I expect the daily scheduler to recompute indicators for the last 24 h at 02:00 UTC
  So that the latest data drives alerts and reports

  Scenario ID: TEST-09
    Given the system clock shows 02:15 UTC
    When the scheduler job runs
    Then at least one IndicatorResult row must have been recomputed with target_date yesterday

Feature: SHA‑256 checksum verification
  As a security‑conscious developer
  I want every ingested raster bundle to have a recorded SHA‑256 hash
  So that we can detect corrupt downloads

  Scenario ID: TEST-10
    Given a CHIRPS ingestion job downloads a .tif.gz file
    When the job finishes
    Then the Dataset record must contain a "checksum_sha256" field
    And a separate verification job must confirm the hash matches the file