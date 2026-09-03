class AddLastActiveAtToSessions < ActiveRecord::Migration[8.1]
  def change
    add_column :sessions, :last_active_at, :datetime

    up_only do
      # Sessions that predate this column have no activity record. Their
      # creation time is the only honest thing to date them from, and it errs
      # toward expiring sooner rather than granting everyone a fresh fortnight.
      execute "UPDATE sessions SET last_active_at = created_at"
    end

    change_column_null :sessions, :last_active_at, false
    # The nightly prune scans on this column.
    add_index :sessions, :last_active_at
  end
end
