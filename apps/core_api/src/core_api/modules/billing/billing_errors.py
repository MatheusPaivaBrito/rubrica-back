class BillingError(Exception):
    """Base error safe to expose at the HTTP boundary."""


class BillingNotFoundError(BillingError):
    pass


class BillingConflictError(BillingError):
    pass


class BillingConfigurationError(BillingError):
    pass


class BillingProviderError(BillingError):
    pass


class BillingSignatureError(BillingError):
    pass
