module Keepsake
  # A bucket with no index.json. Not a failure -- an ordinary state, and the
  # common one for a generic app where somebody connects a plain bucket of
  # videos. Callers turn this into an explanation, never a 500.
  class CatalogMissing < StorageError; end
end
