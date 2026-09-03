# Who a library belongs to.
#
# Libraries are owned here rather than by a person so that more than one person
# can see them, and so that an archive outlives whichever account happened to
# add it. Everyone is in exactly one, alone or otherwise -- an invitation is how
# somebody joins yours.
#
# There are deliberately no roles yet. Everyone in an organization can view and
# edit its libraries, which includes the stored bucket credentials: inviting
# somebody is handing them the keys, not a viewing pass.
class Organization < ApplicationRecord
  has_many :users, dependent: :nullify
  has_many :libraries, dependent: :destroy
  has_many :invites, dependent: :destroy

  normalizes :name, with: ->(n) { n&.strip.presence }
  validates :name, presence: true
end
