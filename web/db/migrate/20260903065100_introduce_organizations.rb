# Libraries move from being owned by a person to being owned by an organization.
#
# Even alone you are in one: it is what an invitation joins you to, and what a
# library belongs to, so sharing later is a matter of adding people rather than
# reshaping anything. Existing data is carried across in place -- nobody
# re-enters bucket credentials because of this.
class IntroduceOrganizations < ActiveRecord::Migration[8.1]
  def up
    create_table :organizations do |t|
      t.string :name, null: false
      t.timestamps
    end

    add_reference :users, :organization, foreign_key: true
    add_reference :libraries, :organization, foreign_key: true
    add_reference :invites, :organization, foreign_key: true

    # One organization per existing user, named after the address they signed
    # up with. It shows in the header, so it is meant to be renamed:
    # bin/rails keepsake:org:rename.
    execute <<~SQL
      INSERT INTO organizations (name, created_at, updated_at)
      SELECT split_part(email_address, '@', 1), NOW(), NOW() FROM users ORDER BY id;
    SQL

    # Pair them back up in the same order they were created in.
    execute <<~SQL
      UPDATE users SET organization_id = paired.org_id
      FROM (
        SELECT u.id AS user_id, o.id AS org_id
        FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn FROM users) u
        JOIN (SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn FROM organizations) o
          ON o.rn = u.rn
      ) paired
      WHERE users.id = paired.user_id;
    SQL

    # A library joins the organization of whoever owned it.
    execute <<~SQL
      UPDATE libraries SET organization_id = users.organization_id
      FROM users WHERE users.id = libraries.user_id;
    SQL

    # Unclaimed invitations point at their creator's organization. One with no
    # creator predates any user and cannot be honoured now that claiming means
    # joining something, so it is expired rather than left to fail confusingly.
    execute <<~SQL
      UPDATE invites SET organization_id = users.organization_id
      FROM users WHERE users.id = invites.created_by_id;
    SQL
    execute <<~SQL
      UPDATE invites SET expires_at = NOW() - INTERVAL '1 second'
      WHERE organization_id IS NULL AND claimed_at IS NULL;
    SQL

    change_column_null :users, :organization_id, false
    change_column_null :libraries, :organization_id, false

    # Who added it, kept for the audit trail now that a library outlives any one
    # person's claim on it.
    rename_column :libraries, :user_id, :created_by_id
    # Nullable now: the person who added a library may since have left, and the
    # library belongs to the organization regardless.
    change_column_null :libraries, :created_by_id, true

    # Labels are unique within an organization now, not within a person.
    remove_index :libraries, column: [ :created_by_id, :label ]
    add_index :libraries, [ :organization_id, :label ], unique: true
  end

  def down
    add_index :libraries, [ :created_by_id, :label ], unique: true
    remove_index :libraries, column: [ :organization_id, :label ]
    rename_column :libraries, :created_by_id, :user_id
    remove_reference :invites, :organization
    remove_reference :libraries, :organization
    remove_reference :users, :organization
    drop_table :organizations
  end
end
