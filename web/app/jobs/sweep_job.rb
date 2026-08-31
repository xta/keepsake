class SweepJob < ApplicationJob
  queue_as :default

  # One at a time. A sweep decodes video frames, and this app shares a small
  # server with other things; several at once would starve them.
  limits_concurrency to: 1, key: ->(library) { "sweep" }, duration: 30.minutes

  def perform(library)
    library.update!(sweep_state: "running", sweep_message: "Looking at the bucket",
                    sweep_started_at: Time.current, sweep_finished_at: nil)

    sweep = Keepsake::Sweep.new(library)
    result = sweep.apply(progress: ->(message) { library.update_column(:sweep_message, message) })

    Keepsake::CatalogSync.new(library).call(force: true)

    library.update!(
      sweep_state: "done",
      sweep_message: summarise(result),
      sweep_finished_at: Time.current
    )
  rescue Keepsake::StorageError, StandardError => e
    library.update!(sweep_state: "failed", sweep_message: e.message, sweep_finished_at: Time.current)
    raise if e.is_a?(StandardError) && !e.is_a?(Keepsake::StorageError)
  end

  private
    def summarise(result)
      parts = []
      parts << "#{result[:adopted].size} adopted" if result[:adopted].any?
      parts << "#{result[:backfilled].size} dated" if result[:backfilled].any?
      parts << "#{result[:thumbnailed].size} thumbnailed" if result[:thumbnailed].any?
      parts << "nothing to do" if parts.empty?
      parts << result[:log].first if result[:log].any?
      parts.join(", ")
    end
end
