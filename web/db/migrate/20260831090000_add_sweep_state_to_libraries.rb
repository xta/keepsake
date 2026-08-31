class AddSweepStateToLibraries < ActiveRecord::Migration[8.1]
  # A sweep reads every sidecar and may decode a frame per video, so it runs as
  # a background job. These columns are how the page knows what it is doing.
  def change
    add_column :libraries, :sweep_state, :string
    add_column :libraries, :sweep_message, :string
    add_column :libraries, :sweep_started_at, :datetime
    add_column :libraries, :sweep_finished_at, :datetime
  end
end
