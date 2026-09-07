// jest-expo installs Expo Winter's lazy native fetch, which leaves pending
// handles/warnings after tests when read late. Keep React Native/Node fetch
// as the base under Jest by opting out of the Winter fetch replacement.
module.exports = () => {
  process.env.EXPO_PUBLIC_USE_RN_FETCH = "1";
};
